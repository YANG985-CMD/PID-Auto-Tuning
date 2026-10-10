#!/usr/bin/env python3
"""Build/run a bounded CAN internal-loopback SRAM diagnostic, no Flash writes.

Motor power must already be physically disconnected. No CAN adapter is opened;
the guest does not initialize GPIO/PWM and does not transmit external CAN frames.
This overwrites SRAM and resets the chip; it is not passive observation.
"""
import argparse
import json
import struct
import subprocess
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
import stm32_actor_pil as pil

FIELDS = ("magic schema state error expected received standard extended dlc_mask "
          "cccr test nbtp psr ecr ir cycles rcc_cfgr rcc_ccipr "
          "tim1_cr1 tim1_ccer tim1_bdtr gpio_clock f0s txbrp tx0 tx1 rx0 rx1").split()
MODE = "can-internal-loopback"


def compile_guest(args, stem, entry_symbol, mode, frames, external):
    """Compile only a caller-selected bundled guest; no user C source argument."""
    from elftools.elf.elffile import ELFFile
    out = pil.fresh_dir(args.output)
    compiler_root = Path(args.arm_bin).resolve()
    cmsis = Path(args.cmsis_root).resolve()
    device = cmsis / "Device/ST/STM32G4xx/Include"
    core = cmsis / "Include"
    if not (device / "stm32g431xx.h").is_file() or not (core / "core_cm4.h").is_file():
        raise ValueError("Use a STM32G4 CMSIS tree with G431 device and Cortex-M4 headers")
    compiler, linker = compiler_root / "armclang.exe", compiler_root / "armlink.exe"
    if not compiler.is_file():
        compiler, linker = compiler_root / "armclang", compiler_root / "armlink"
    logs = []

    def command(argv):
        result = subprocess.run([str(a) for a in argv], cwd=out, capture_output=True, text=True)
        logs.append(result.stdout + result.stderr)
        (out / "build.log").write_text("\n".join(logs), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Diagnostic target build failed; inspect build.log")

    common = ["--target=arm-arm-none-eabi", "-mcpu=cortex-m4", "-mfloat-abi=soft",
              "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-ffreestanding",
              "-DSTM32G431xx", "-I", device, "-I", core]
    for name, source in (("entry", "stm32_" + stem + ".S"), ("guest", "stm32_" + stem + ".c")):
        command([compiler, *common, "-c", SKILL / "firmware" / source, "-o", out / (name + ".o")])
    (out / "guest.sct").write_text("""LR_RAM 0x20000000 0x4000 {
  ER_RAM 0x20000000 0x4000 {
    entry.o (RESET, +First)
    .ANY (+RO)
    .ANY (+RW +ZI)
  }
}
""", encoding="ascii")
    elf = out / (stem + ".axf")
    command([linker, "--cpu=Cortex-M4", "--entry=" + entry_symbol, "--scatter", out / "guest.sct",
             "--map", "--symbols", "--list", out / "image.map", "--output", elf,
             out / "entry.o", out / "guest.o"])
    data = bytearray(pil.CODE_LIMIT - pil.RAM)
    high = pil.RAM
    with elf.open("rb") as handle:
        e = ELFFile(handle)
        entry = int(e.header["e_entry"])
        for segment in e.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            address, size = int(segment["p_vaddr"]), int(segment["p_memsz"])
            if not pil.RAM <= address < pil.CODE_LIMIT or address + size > pil.CODE_LIMIT:
                raise ValueError("Diagnostic ELF segment outside reserved SRAM")
            content = segment.data()
            data[address - pil.RAM:address - pil.RAM + len(content)] = content
            high = max(high, address + size)
    data = bytes(data[:high - pil.RAM])
    contract = dict(schema_version=1, mode=mode, load_address=pil.RAM,
                    mailbox_address=pil.MAILBOX, stack_bottom=pil.STACK_BOTTOM,
                    stack_top=pil.STACK_TOP, entry=entry, image_sha256=pil.sha(data),
                    image_bytes=len(data), expected_frames=frames, external_can=external,
                    motor_output=False, flash_programming=False,
                    device_header_sha256=pil.sha((device / "stm32g431xx.h").read_bytes()))
    return out, contract, data


def build(args):
    out, contract, data = compile_guest(args, "can_loopback", "can_diag_entry", MODE, 64, False)
    validate_image(contract, data)
    (out / "can-loopback.bin").write_bytes(data)
    pil.save_json(out / "can-build.json", contract)
    return contract


def validate_image(contract, image):
    expected = (pil.RAM, pil.MAILBOX, pil.STACK_BOTTOM, pil.STACK_TOP)
    actual = tuple(contract.get(k) for k in ("load_address", "mailbox_address", "stack_bottom", "stack_top"))
    entry = contract.get("entry", 0)
    if (contract.get("schema_version") != 1 or contract.get("mode") != MODE
            or contract.get("external_can") is not False or contract.get("motor_output") is not False
            or contract.get("flash_programming") is not False or contract.get("expected_frames") != 64
            or actual != expected or not 512 < len(image) <= pil.CODE_LIMIT - pil.RAM
            or contract.get("image_bytes") != len(image)
            or contract.get("image_sha256") != pil.sha(image)
            or not isinstance(entry, int) or not entry & 1
            or not pil.RAM + 512 <= (entry & ~1) < pil.RAM + len(image)
            or struct.unpack_from("<II", image) != (pil.STACK_TOP, entry)):
        raise ValueError("Invalid SRAM-only internal-loopback image contract")


def analyze(data):
    if len(data) != 4 * len(FIELDS):
        raise ValueError("Incomplete CAN diagnostic mailbox")
    r = dict(zip(FIELDS, struct.unpack("<" + "I" * len(FIELDS), data)))
    if (tuple(r[k] for k in ("magic", "schema", "state", "error", "expected", "received",
                            "standard", "extended", "dlc_mask"))
            != (0x43414E31, 1, 2, 0, 64, 64, 32, 32, 0x1FF)
            or r["cccr"] & 0xA0 != 0xA0 or not r["test"] & 0x10
            or r["nbtp"] != 0x10904 or not 0 < r["cycles"] < 48000000
            or r["rcc_cfgr"] & 0x7FC != 4 or r["rcc_ccipr"] & 0x03000000 != 0x02000000
            or r["tim1_cr1"] or r["tim1_ccer"] or r["tim1_bdtr"]
            or r["gpio_clock"] or r["f0s"] & 0x0200000F or r["txbrp"]
            or r["ecr"] & 0xFFFF or r["psr"] & 0xE7):
        raise ValueError("CAN diagnostic completion, mode, data or safety check failed: " + str(r))
    return r


def safe_registers(target):
    return dict(tim1_cr1=target.read32(0x40012C00), tim1_ccer=target.read32(0x40012C20),
                tim1_bdtr=target.read32(0x40012C44), gpio_clocks=target.read32(0x4002104C))


def run(args):
    # Reject missing confirmations and mismatched manifests before opening a probe.
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError("Requires existing physical power-disconnection and reset/SRAM acknowledgement")
    source = Path(args.build).resolve()
    contract = json.loads((source / "can-build.json").read_text(encoding="utf-8"))
    image = (source / "can-loopback.bin").read_bytes()
    validate_image(contract, image)
    out = pil.fresh_dir(args.output)
    from pyocd.core.target import Target
    session = pil.session(out)
    target, before, supported_target = None, None, False
    report = dict(schema_version=1, mode=MODE, internal_loopback_verified=False,
                  external_can_link_verified=False, power_disconnected_confirmed_by_user=True,
                  flash_programming=False, motor_output=False, original_application_resumed=False)
    try:
        session.open()
        target = session.target
        report["identity"] = pil.identity(target)
        supported_target = True
        target.halt()
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("Unable to halt MCU before diagnostic")
        before = bytes(target.read_memory_block8(pil.FLASH, pil.FLASH_BYTES))
        # Keep this private content in memory; never publish or dump the firmware.
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        safe = safe_registers(target)
        if target.get_state() != Target.State.HALTED or any(safe.values()):
            raise RuntimeError("MCU reset/PWM/GPIO-clock prerequisites failed")
        target.write_memory_block8(pil.RAM, bytes(pil.STACK_TOP - pil.RAM))
        target.write_memory_block8(pil.RAM, image)
        target.write_memory_block8(pil.STACK_BOTTOM, bytes([0xA5]) * (pil.STACK_TOP - pil.STACK_BOTTOM))
        if bytes(target.read_memory_block8(pil.RAM, len(image))) != image:
            raise RuntimeError("CAN diagnostic SRAM image readback failed")
        target.selected_core.write_core_registers_raw(
            ["msp", "psp", "control", "primask", "basepri", "faultmask", "xpsr", "pc"],
            [pil.STACK_TOP, pil.STACK_TOP, 0, 1, 0, 0, 0x01000000, contract["entry"]])
        target.write32(0xE000ED08, pil.RAM)
        target.resume()  # Only the internal-loopback SRAM entry, never the Flash application.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and target.get_state() == Target.State.RUNNING:
            time.sleep(0.01)
        target.halt()
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("CAN diagnostic did not halt")
        data = bytes(target.read_memory_block8(pil.MAILBOX, 4 * len(FIELDS)))
        # Preserve the bounded mailbox on failed tests as diagnostic data.
        pil.save_json(out / "mailbox.json", dict(zip(FIELDS, struct.unpack("<" + "I" * len(FIELDS), data))))
        report["mailbox"] = analyze(data)
        if any(safe_registers(target).values()):
            raise RuntimeError("Unexpected PWM or GPIO activation during CAN diagnostic")
        paint = bytes(target.read_memory_block8(pil.STACK_BOTTOM, pil.STACK_TOP - pil.STACK_BOTTOM))
        first = next((i for i, byte in enumerate(paint) if byte != 0xA5), len(paint))
        report["stack_observed_bytes"] = len(paint) - first
        report["stack_bottom_fence_intact"] = paint[:64] == bytes([0xA5]) * 64
        if not report["stack_bottom_fence_intact"]:
            raise RuntimeError("CAN diagnostic stack fence failed")
        report.update(internal_loopback_verified=True, image_bytes=len(image),
                      image_sha256=pil.sha(image), nominal_bitrate=500000, nominal_clock_hz=16000000)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if target is not None and supported_target:
            try:
                # Stop every diagnostic peripheral; leave original Flash application paused.
                target.reset_and_halt(Target.ResetType.SYSRESETREQ)
                report["core_left_halted"] = target.get_state() == Target.State.HALTED
                report["final_registers"] = safe_registers(target)
                if before is not None:
                    report["flash_unchanged"] = bytes(target.read_memory_block8(pil.FLASH, pil.FLASH_BYTES)) == before
                if (not report["core_left_halted"] or any(report["final_registers"].values())
                        or report.get("flash_unchanged") is not True):
                    report["internal_loopback_verified"] = False
                    report.setdefault("error", "Final halt/PWM/Flash check failed")
            except Exception as exc:
                report["internal_loopback_verified"] = False
                report["cleanup_error"] = str(exc)
        try:
            session.close()
        except Exception as exc:
            report["internal_loopback_verified"] = False
            report["disconnect_error"] = str(exc)
        pil.save_json(out / "can-result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    b = modes.add_parser("build", help="offline target compile, no probe access")
    b.add_argument("--arm-bin", required=True)
    b.add_argument("--cmsis-root", required=True)
    b.add_argument("--output", required=True)
    r = modes.add_parser("run", help="internal loopback in SRAM, no external frames")
    r.add_argument("--build", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--power-stage-disconnected", action="store_true")
    r.add_argument("--reset-and-halt-ack", action="store_true")
    args = parser.parse_args()
    report = build(args) if args.mode == "build" else run(args)
    print(json.dumps(report, indent=2, allow_nan=False))
    if args.mode == "run" and not report["internal_loopback_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
