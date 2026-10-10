#!/usr/bin/env python3
"""Read-only RAM evidence from the audited STM32G4 SpeedLoop image.

The default ``map`` command only parses the Keil map file and never opens a
debug probe.  The ``read`` command attaches to exactly one probe and briefly
halts the core to read the variables emitted by the working SpeedLoop image.
It refuses to run without an explicit physical power-disconnected
acknowledgement.  It never resets, writes SRAM/Flash, changes peripherals, or
changes gains.  By default the core is left halted after the read so that the
operator can inspect the result before deciding whether to resume it.

Use a task directory under E:\\simulink\\_codex_tmp for output.  The map file
and the AXF are private board artifacts and must not be uploaded to GitHub.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

EXPECTED = {"a": 2021.08, "b": 2028.78, "c": 2024.63}
DEFAULT_TOLERANCE_COUNTS = 4.0
SYMBOLS = {
    "Motor_state": ("u8", "motor_state"),
    "ADC_offset": ("u8", "adc_offset_complete"),
    "IA_Offset": ("u16", "ia_offset"),
    "IB_Offset": ("u16", "ib_offset"),
    "IC_Offset": ("u16", "ic_offset"),
    "Ia": ("f32", "ia"),
    "Ib": ("f32", "ib"),
    "Ic": ("f32", "ic"),
    "Vbus": ("f32", "vbus"),
    "HallSpeed": ("f32", "hall_speed"),
}
MAP_LINE = re.compile(
    r"^\s*(?P<name>Motor_state|ADC_offset|IA_Offset|IB_Offset|IC_Offset|"
    r"Ia|Ib|Ic|Vbus|HallSpeed)\s+0x(?P<address>[0-9A-Fa-f]+)\b"
)


def parse_map(path: Path) -> dict[str, dict[str, object]]:
    """Parse only the audited symbols from a Keil map file."""
    found: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = MAP_LINE.match(line)
        if match:
            name = match.group("name")
            kind, key = SYMBOLS[name]
            found[key] = {"source": name, "address": int(match.group("address"), 16), "type": kind}
    missing = [key for _, key in SYMBOLS.values() if key not in found]
    if missing:
        raise ValueError("map is missing audited symbols: " + ", ".join(missing))
    return found


def decode(kind: str, raw: bytes) -> int | float:
    if kind == "u8":
        return raw[0]
    if kind == "u16":
        return struct.unpack("<H", raw)[0]
    if kind == "f32":
        return struct.unpack("<f", raw)[0]
    raise ValueError("unsupported symbol type: " + kind)


def map_report(args: argparse.Namespace) -> dict[str, object]:
    symbols = parse_map(Path(args.map).resolve())
    return {
        "schema_version": 1,
        "mode": "speedloop-map-symbols",
        "map": str(Path(args.map).resolve()),
        "image": str(Path(args.image).resolve()) if args.image else None,
        "symbols": symbols,
        "expected_zero_adc_counts": EXPECTED,
        "comparison_tolerance_counts": args.tolerance,
        "hardware_access": False,
    }


def _read(target, address: int, kind: str) -> int | float:
    size = {"u8": 1, "u16": 2, "f32": 4}[kind]
    return decode(kind, bytes(target.read_memory_block8(address, size)))


def read_report(args: argparse.Namespace) -> dict[str, object]:
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError(
            "read requires --power-stage-disconnected and --reset-and-halt-ack; "
            "this command halts the live core briefly"
        )
    symbols = parse_map(Path(args.map).resolve())
    try:
        from stm32_actor_pil import identity, session
    except ImportError as exc:
        raise RuntimeError("run from the skill scripts directory so pyOCD helpers can be imported") from exc

    out = Path(args.output).resolve() if args.output else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            raise ValueError("refusing to overwrite output: " + str(out))
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "speedloop-read-only-ram",
        "map": str(Path(args.map).resolve()),
        "power_stage_disconnected_confirmed_by_user": True,
        "reset_and_halt_acknowledged": True,
        "flash_programming": False,
        "sram_write": False,
        "peripheral_write": False,
        "gains_written": False,
        "motor_start_requested": False,
        "resume_requested": bool(args.resume_after_read),
        "verified": False,
    }
    debug = None
    was_running = None
    try:
        debug = session(out.parent if out else Path.cwd())
        debug.open()
        target = debug.target
        report["identity"] = identity(target)
        was_running = target.get_state().name == "RUNNING"
        report["state_before"] = target.get_state().name
        target.halt()
        if target.get_state().name != "HALTED":
            raise RuntimeError("debug probe did not halt the core")
        values = {key: _read(target, int(spec["address"]), str(spec["type"]))
                  for key, spec in symbols.items()}
        report["values"] = values
        offsets = {phase: float(values[key]) for phase, key in (("a", "ia_offset"), ("b", "ib_offset"), ("c", "ic_offset"))}
        report["offsets"] = offsets
        report["adc_offset_complete"] = bool(values["adc_offset_complete"])
        report["offset_error_counts"] = {phase: offsets[phase] - EXPECTED[phase] for phase in EXPECTED}
        report["offsets_within_reference_tolerance"] = all(
            abs(report["offset_error_counts"][phase]) <= args.tolerance for phase in EXPECTED
        )
        report["state_after_read"] = target.get_state().name
        if args.resume_after_read:
            target.resume()
            report["state_after_resume"] = target.get_state().name
        else:
            report["core_left_halted"] = target.get_state().name == "HALTED"
        report["verified"] = bool(report.get("core_left_halted", False) or args.resume_after_read)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if debug is not None:
            try:
                debug.close()
            except Exception as exc:
                report["close_error"] = str(exc)
        if out:
            out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p_map = sub.add_parser("map", help="parse the private Keil map without hardware access")
    p_map.add_argument("--map", required=True)
    p_map.add_argument("--image")
    p_map.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_COUNTS)
    p_read = sub.add_parser("read", help="read the audited RAM variables through STLink")
    p_read.add_argument("--map", required=True)
    p_read.add_argument("--output")
    p_read.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_COUNTS)
    p_read.add_argument("--power-stage-disconnected", action="store_true")
    p_read.add_argument("--reset-and-halt-ack", action="store_true",
                        help="acknowledge that attach briefly halts the live core")
    p_read.add_argument("--resume-after-read", action="store_true",
                        help="resume the core after the read; use only with power physically disconnected")
    args = parser.parse_args()
    try:
        report = map_report(args) if args.mode == "map" else read_report(args)
    except Exception as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report.get("verified", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
