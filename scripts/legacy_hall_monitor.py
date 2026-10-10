#!/usr/bin/env python3
"""Read-only monitor for the legacy STM32G4 Hall FOC telemetry stream.

The original board firmware sends 24-byte little-endian packets at 921600 8N1:
five float32 values followed by two reserved zero bytes and ``0x80 0x7f``.
This tool never writes to the serial port. It is intentionally a shadow-only
adapter: it cannot start the motor or apply TD3 gains.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path


PACKET_SIZE = 24
TAIL = b"\x00\x00\x80\x7f"


def decode_packet(packet: bytes) -> dict[str, float | int]:
    if len(packet) != PACKET_SIZE or packet[20:24] != TAIL:
        raise ValueError("invalid legacy packet tail")
    values = struct.unpack("<5f", packet[:20])
    if not all(float(value) == float(value) and abs(value) != float("inf") for value in values):
        raise ValueError("non-finite legacy telemetry")
    return {
        "ia_a": values[0],
        # The legacy field is a TIM4 capture period, despite its old variable
        # name HallTemp. Keep the physical meaning explicit in the adapter.
        "hall_period_ticks": values[1],
        "hall_theta_rad": values[2],
        "speed_ref_rpm": values[3],
        "hall_speed_rpm": values[4],
    }


def emit(record: dict, output) -> None:
    output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    output.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="USB-UART COM port connected to PB10/PB11")
    parser.add_argument("--duration", type=float, default=10.0, help="capture duration in seconds")
    parser.add_argument("--max-frames", type=int, default=0, help="stop after this many valid frames; 0 means no limit")
    parser.add_argument("--output", type=Path, help="JSONL output file; stdout when omitted")
    args = parser.parse_args()
    if args.duration <= 0 or args.max_frames < 0:
        parser.error("duration must be positive and max-frames must be non-negative")

    try:
        import serial
    except ImportError as exc:
        raise SystemExit("install pyserial before using the legacy monitor") from exc

    stream = open(args.output, "w", encoding="utf-8", newline="\n") if args.output else sys.stdout
    buffer = bytearray()
    valid = rejected = 0
    deadline = time.monotonic() + args.duration
    try:
        # Opening a serial port is the only side effect. No command bytes are
        # ever written, and DTR/RTS are kept inactive.
        with serial.Serial(
            args.port,
            921600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            write_timeout=0.1,
            dsrdtr=False,
            rtscts=False,
        ) as port:
            port.dtr = False
            port.rts = False
            while time.monotonic() < deadline:
                chunk = port.read(256)
                if chunk:
                    buffer.extend(chunk)
                while len(buffer) >= PACKET_SIZE:
                    candidate = bytes(buffer[:PACKET_SIZE])
                    if candidate[20:24] != TAIL:
                        del buffer[0]
                        rejected += 1
                        continue
                    del buffer[:PACKET_SIZE]
                    try:
                        payload = decode_packet(candidate)
                    except ValueError:
                        rejected += 1
                        continue
                    valid += 1
                    emit({"host_time_s": time.time(), **payload}, stream)
                    if args.max_frames and valid >= args.max_frames:
                        deadline = 0
                        break
    finally:
        if args.output:
            stream.close()
    print(json.dumps({"valid_frames": valid, "rejected_bytes": rejected}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

