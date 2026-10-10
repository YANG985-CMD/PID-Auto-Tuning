#!/usr/bin/env python3
"""Build an Actor RAM image and run computation-only PIL on STM32G431/G441.

No Flash programming API is used. Run resets the target, replaces SRAM, and
leaves the core halted. Motor power must be physically disconnected first.
All artifacts, including the private original-Flash backup, use explicit dirs.
"""
import argparse
import hashlib
import json
import math
import struct
import subprocess
import time
from pathlib import Path

RAM = 0x20000000
CODE_LIMIT = 0x20004000
MAILBOX = 0x20004400
STACK_BOTTOM = 0x20004C00
STACK_TOP = 0x20005000
FLASH = 0x08000000
FLASH_BYTES = 128 * 1024
MAGIC = 0x50494C31
FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def fresh_dir(value):
    path = Path(value).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError("Use a new empty task artifact directory")
    return path


def references(value):
    rows = json.loads(Path(value).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError("PIL supports 1..40 reference vectors")
    for row in rows:
        for key, count in (("raw_state", 10), ("action", 2), ("gains", 2)):
            values = row.get(key)
            if (not isinstance(values, list) or len(values) != count
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                               and math.isfinite(x) for x in values)):
                raise ValueError("Invalid reference vector")
    return rows


def build(args):
    from actor_codegen import export, cfloat
    from elftools.elf.elffile import ELFFile
    rows = references(args.reference)
    out = fresh_dir(args.output)
    actor = export(args.model, out)  # Regenerate arithmetic from JSON; no user C input.
    header = "#define PIL_VECTORS %d\nstatic const float pil_inputs[PIL_VECTORS][10] = {\n" % len(rows)
    header += ",\n".join("{" + ",".join(cfloat(x) for x in r["raw_state"]) + "}" for r in rows)
    (out / "pil_vectors.h").write_text(header + "\n};\n", encoding="utf-8", newline="\n")
    save_json(out / "reference.json", rows)
    tool = Path(args.arm_bin).resolve()
    compiler, linker = tool / "armclang.exe", tool / "armlink.exe"
    # Native non-Windows Arm Compiler installations use names without .exe.
    if not compiler.is_file():
        compiler, linker = tool / "armclang", tool / "armlink"
    logs = []

    def command(argv):
        result = subprocess.run([str(x) for x in argv], cwd=out, capture_output=True, text=True)
        logs.append(result.stdout + result.stderr)
        (out / "build.log").write_text("\n".join(logs), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Target build failed; inspect build.log")

    common = ["--target=arm-arm-none-eabi", "-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16",
              "-mfloat-abi=hard", "-O2", "-ffp-contract=off", "-fno-fast-math",
              "-g", "-I", out]
    for source, name in ((out / "motor_actor.c", "actor.o"),
                         (FIRMWARE / "stm32_actor_pil.c", "guest.o"),
                         (FIRMWARE / "stm32_actor_pil.S", "entry.o")):
        command([compiler, *common, "-c", source, "-o", out / name])
    scatter = """LR_RAM 0x20000000 0x4000 {
  ER_RAM 0x20000000 0x4000 {
    entry.o (RESET, +First)
    .ANY (+RO)
    .ANY (+RW +ZI)
  }
}
"""
    (out / "pil.sct").write_text(scatter, encoding="ascii")
    elf = out / "actor-pil.axf"
    command([linker, "--cpu=Cortex-M4", "--entry=pil_entry", "--scatter", out / "pil.sct",
             "--map", "--symbols", "--callgraph", "--info=sizes,totals", "--list", out / "image.map",
             "--output", elf, out / "entry.o", out / "guest.o", out / "actor.o"])
    image = bytearray(CODE_LIMIT - RAM)
    high = RAM
    with elf.open("rb") as handle:
        e = ELFFile(handle)
        entry = int(e.header["e_entry"])
        for segment in e.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            address, size = int(segment["p_vaddr"]), int(segment["p_memsz"])
            if not RAM <= address < CODE_LIMIT or address + size > CODE_LIMIT:
                raise ValueError("ELF load segment outside reserved RAM")
            data = segment.data()
            image[address - RAM:address - RAM + len(data)] = data
            high = max(high, address + size)
    image = bytes(image[:high - RAM])
    if (len(image) < 512 or struct.unpack_from("<II", image) != (STACK_TOP, entry)
            or not RAM <= (entry & ~1) < CODE_LIMIT):
        raise ValueError("Unexpected RAM vector/entry contract")
    (out / "actor-pil.bin").write_bytes(image)
    report = dict(schema_version=1, target="stm32g431-g441-128kb", entry=entry,
                  load_address=RAM, image_bytes=len(image), reserved_code_bytes=CODE_LIMIT - RAM,
                  mailbox_address=MAILBOX, stack_bottom=STACK_BOTTOM, stack_top=STACK_TOP,
                  vectors=len(rows), float_abi="hard-fpv4-sp-d16", fp_contract=False,
                  image_sha256=sha(image), reference_sha256=sha((out / "reference.json").read_bytes()),
                  actor=actor, flash_programming=False, motor_output=False,
                  processor_in_loop_verified=False)
    save_json(out / "pil-build.json", report)
    return report


def session(out):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.session import Session
    probes = ConnectHelper.get_all_connected_probes(blocking=False)
    if len(probes) != 1:
        raise ValueError("Exactly one debug probe must be connected")
    # Generic core, no vendor pack sequences, no mass erase, no automatic resume.
    # The newly empty output directory also prevents auto-loading user scripts.
    options = dict(target_override="cortex_m", connect_mode="attach", frequency=1000000,
                   auto_unlock=False, resume_on_disconnect=False, no_config=True,
                   project_dir=str(out), **{"cache.enable_memory": False,
                                            "cache.enable_register": False})
    return Session(probes[0], auto_open=False, options=options)


def identity(target):
    cpuid = target.read32(0xE000ED00)
    device = target.read32(0xE0042000)
    capacity = target.read16(0x1FFF75E0)
    if ((cpuid >> 4) & 0xFFF) != 0xC24 or (device & 0xFFF) != 0x468 or capacity != 128:
        raise ValueError("Target is not the supported STM32G431/G441 128KB Cortex-M4")
    return dict(cpuid=hex(cpuid), dbgmcu_idcode=hex(device), flash_kb=capacity)


def probe(args):
    out = fresh_dir(args.output)
    s = session(out)
    try:
        s.open()
        report = dict(schema_version=1, identity=identity(s.target), state=s.target.get_state().name,
                      reset=False, memory_loaded=False, flash_programming=False, serial_opened=False)
        save_json(out / "probe.json", report)
        return report
    finally:
        s.close()


def run(args):
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError("Physically disconnect motor power and acknowledge reset/SRAM replacement first")
    source = Path(args.build).resolve()
    contract = json.loads((source / "pil-build.json").read_text(encoding="utf-8"))
    image = (source / "actor-pil.bin").read_bytes()
    rows = references(source / "reference.json")
    expected = (RAM, MAILBOX, STACK_BOTTOM, STACK_TOP)
    actual = tuple(contract.get(k) for k in ("load_address", "mailbox_address", "stack_bottom", "stack_top"))
    if (actual != expected or len(image) > CODE_LIMIT - RAM or len(image) < 512
            or sha(image) != contract["image_sha256"]
            or sha((source / "reference.json").read_bytes()) != contract["reference_sha256"]
            or struct.unpack_from("<II", image) != (STACK_TOP, contract["entry"])
            or not RAM + 512 <= (contract["entry"] & ~1) < RAM + len(image)
            or not contract["entry"] & 1
            or contract["vectors"] != len(rows)):
        raise ValueError("PIL image/reference contract mismatch")
    out = fresh_dir(args.output)
    from pyocd.core.target import Target
    s = session(out)
    target = None
    before = None
    report = dict(schema_version=1, mode="ram-only-computation-pil", flash_programming=False,
                  motor_power_disconnected_by_user=True, motor_output=False,
                  processor_in_loop_verified=False, motor_control_approved=False)
    try:
        s.open()
        target = s.target
        report["identity"] = identity(target)
        target.halt()
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("Could not halt target")
        before = bytes(target.read_memory_block8(FLASH, FLASH_BYTES))
        # This is private firmware, never publish it. Save before any reset/SRAM write.
        (out / "original-flash-private.bin").write_bytes(before)
        report["original_flash_sha256"] = sha(before)
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("Reset did not halt target; abort without loading")
        bdtr, ccer = target.read32(0x40012C44), target.read32(0x40012C20)
        if bdtr & 0x8000 or ccer:
            raise RuntimeError("TIM1 outputs were not off after reset")
        report["tim1_outputs_disabled"] = True
        rcc_cfgr = target.read32(0x40021008)
        report["rcc_cfgr_after_reset"] = hex(rcc_cfgr)
        if rcc_cfgr & 0xC == 0x4 and rcc_cfgr & 0xF0 == 0:
            report["core_clock_nominal_hz"] = 16000000
        # Entire guest region is SRAM. Never use FileProgrammer or FlashLoader.
        target.write_memory_block8(RAM, bytes(STACK_TOP - RAM))
        target.write_memory_block8(RAM, image)
        target.write_memory_block8(STACK_BOTTOM, bytes([0xA5]) * (STACK_TOP - STACK_BOTTOM))
        if bytes(target.read_memory_block8(RAM, len(image))) != image:
            raise RuntimeError("RAM image readback mismatch")
        core = target.selected_core
        core.write_core_registers_raw(["msp", "psp", "control", "primask", "basepri", "faultmask", "xpsr", "pc"],
                                      [STACK_TOP, STACK_TOP, 0, 1, 0, 0, 0x01000000, contract["entry"]])
        target.write32(0xE000ED08, RAM)  # VTOR: RAM guest fault/interrupt vectors.
        target.resume()                # Executes only the bounded arithmetic guest.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and target.get_state() == Target.State.RUNNING:
            time.sleep(0.01)
        target.halt()
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("PIL target did not halt")
        data = bytes(target.read_memory_block8(MAILBOX, 32 + 24 * len(rows)))
        magic, schema, state, count, bad = struct.unpack_from("<5I", data)
        if (magic, schema, state, count, bad) != (MAGIC, 1, 2, len(rows), 7):
            raise RuntimeError("PIL completion/invalid-input contract failed")
        errors = [0.0, 0.0]
        cycles, observed = [], []
        for index, reference in enumerate(rows):
            ok, elapsed, a0, a1, g0, g1 = struct.unpack_from("<II4f", data, 32 + 24 * index)
            if ok != 1 or elapsed == 0 or not all(math.isfinite(x) for x in (a0, a1, g0, g1)):
                raise RuntimeError("Invalid MCU inference output")
            errors[0] = max(errors[0], *(abs(a - b) for a, b in zip((a0, a1), reference["action"])))
            errors[1] = max(errors[1], *(abs(a - b) for a, b in zip((g0, g1), reference["gains"])))
            cycles.append(elapsed)
            observed.append(dict(index=index, cycles=elapsed, action=[a0, a1], gains=[g0, g1]))
        paint = bytes(target.read_memory_block8(STACK_BOTTOM, STACK_TOP - STACK_BOTTOM))
        first = next((i for i, byte in enumerate(paint) if byte != 0xA5), len(paint))
        report.update(vectors=len(rows), max_action_error=errors[0], max_gain_error=errors[1],
                      cycles_min=min(cycles), cycles_max=max(cycles), cycles_mean=sum(cycles) / len(cycles),
                      stack_reserved_bytes=len(paint), stack_high_water_observed_bytes=len(paint) - first,
                      stack_bottom_fence_intact=paint[:64] == bytes([0xA5]) * 64,
                      invalid_inputs_rejected=["NaN", "Infinity", "out-of-range-gain"],
                      image_bytes=len(image), image_sha256=sha(image),
                      policy_version=contract["actor"]["policy_version"],
                      simulation_only=contract["actor"]["simulation_only"],
                      timing_scope="RAM, reset clock, interrupts masked; not production WCET")
        save_json(out / "mcu-reference-results.json", observed)
        if errors[0] > 2e-6 or errors[1] > 2e-9 or not report["stack_bottom_fence_intact"]:
            raise RuntimeError("MCU parity/stack check failed")
        report["processor_in_loop_verified"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if target is not None:
            try:
                target.halt()
                report["core_left_halted"] = target.get_state() == Target.State.HALTED
                if not report["core_left_halted"]:
                    report["processor_in_loop_verified"] = False
                    report.setdefault("error", "Could not leave the core halted")
                if before is not None:
                    after = bytes(target.read_memory_block8(FLASH, FLASH_BYTES))
                    report["flash_unchanged"] = after == before
                    report["final_flash_sha256"] = sha(after)
                    if after != before:
                        report["processor_in_loop_verified"] = False
                        report["error"] = "Original Flash content changed unexpectedly"
                if report.get("tim1_outputs_disabled") and (target.read32(0x40012C44) & 0x8000
                                                            or target.read32(0x40012C20)):
                    report["processor_in_loop_verified"] = False
                    report.setdefault("error", "Unexpected TIM1 output enable after PIL")
            except Exception as exc:
                report["cleanup_error"] = str(exc)
                report["processor_in_loop_verified"] = False
        try:
            s.close()
        except Exception as exc:
            report["disconnect_error"] = str(exc)
            report["processor_in_loop_verified"] = False
        save_json(out / "pil-result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    p = modes.add_parser("build", help="offline cross-compile; no debug access")
    p.add_argument("--model", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--arm-bin", required=True)
    p.add_argument("--output", required=True)
    p = modes.add_parser("probe", help="read chip identity using attach; no reset")
    p.add_argument("--output", required=True)
    p = modes.add_parser("run", help="reset, execute RAM guest, leave core halted")
    p.add_argument("--build", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--power-stage-disconnected", action="store_true")
    p.add_argument("--reset-and-halt-ack", action="store_true")
    args = parser.parse_args()
    result = {"build": build, "probe": probe, "run": run}[args.mode](args)
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.mode == "run" and not result.get("processor_in_loop_verified"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
