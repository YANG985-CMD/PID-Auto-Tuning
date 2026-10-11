#!/usr/bin/env python3
"""Read-only shadow stream for the legacy 17.SpeedLoop CAN telemetry.

The legacy baseline firmware publishes frames only while it receives the
0x640 host heartbeat.  This tool sends that heartbeat and reconstructs the
0x641..0x646 snapshots, but never sends USER3, BEGIN, GAINS, or a motor
command.  If a running phase output is observed, heartbeat transmission is
stopped so the firmware's existing link-loss stop path is exercised.
"""
import argparse
import json
import math
import struct
import time
from pathlib import Path

MAGIC = 0x42534C31
HEARTBEAT_ID = 0x640
FRAME_IDS = tuple(range(0x641, 0x647))


def decode_snapshot(frames):
    if set(frames) != set(FRAME_IDS) or any(len(frames[i]) != 8 for i in FRAME_IDS):
        raise ValueError('Incomplete SpeedLoop six-frame snapshot')
    first = frames[0x641]
    if first[0] != 0xB1:
        raise ValueError('Unexpected SpeedLoop snapshot marker')
    state, fault, flags = first[1:4]
    elapsed_ms, samples = struct.unpack_from('<HH', first, 4)
    speed, ia = struct.unpack_from('<ff', frames[0x642])
    ib, ic = struct.unpack_from('<ff', frames[0x643])
    vbus, peak = struct.unpack_from('<ff', frames[0x644])
    kp, ki = struct.unpack_from('<ff', frames[0x645])
    host_sequence, hall_edges = struct.unpack('<II', frames[0x646])
    values = (speed, ia, ib, ic, vbus, peak, kp, ki)
    if not all(math.isfinite(x) for x in values):
        raise ValueError('Non-finite SpeedLoop telemetry')
    return {
        'state': state, 'fault': fault, 'stage': flags & 0x7F,
        'phase_enabled': bool(flags & 0x80), 'elapsed_ms': elapsed_ms,
        'sample_counter_mod65536': samples, 'speed_rpm': speed,
        'ia_nominal_a': ia, 'ib_nominal_a': ib, 'ic_nominal_a': ic,
        'bus_nominal_v': vbus, 'peak_nominal_a': peak, 'kp': kp, 'ki': ki,
        'host_sequence': host_sequence, 'hall_edges': hall_edges,
    }


def run(args):
    if not args.allow_live:
        raise ValueError('Shadow CAN access requires explicit --allow-live')
    if not math.isfinite(args.duration) or args.duration < 0:
        raise ValueError('duration must be finite and nonnegative')
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new and empty')
    output.mkdir(parents=True, exist_ok=True)
    try:
        import can
    except ImportError as exc:
        raise RuntimeError('python-can is required; use scripts/requirements-can.txt') from exc
    bus = can.Bus(interface='pcan', channel=args.channel, bitrate=500000,
                  receive_own_messages=False)
    report = {
        'schema_version': 1, 'mode': 'legacy-speedloop-shadow',
        'channel': args.channel, 'bitrate': 500000,
        'observation_only': True, 'motion_commands_sent': 0,
        'gain_commands_sent': 0, 'td3_trainable_transitions': 0,
        'snapshots': 0, 'rx_frames': 0, 'fault_snapshots': 0,
        'motion_detected': False, 'errors': [],
    }
    frames = {}
    next_heartbeat = time.monotonic()
    heartbeat_seq = 0
    stop_deadline = None
    started = time.monotonic()
    try:
        with (output / 'snapshots.jsonl').open('x', encoding='utf-8') as stream:
            while True:
                now = time.monotonic()
                if stop_deadline is None and (args.duration == 0 or now - started < args.duration):
                    if now >= next_heartbeat:
                        heartbeat_seq += 1
                        bus.send(can.Message(arbitration_id=HEARTBEAT_ID,
                                             is_extended_id=False,
                                             data=struct.pack('<II', MAGIC, heartbeat_seq)))
                        next_heartbeat = now + args.heartbeat_ms / 1000.0
                elif stop_deadline is None:
                    # Releasing the heartbeat invokes the firmware link-loss stop path.
                    stop_deadline = now + 0.30
                if stop_deadline is not None and now >= stop_deadline:
                    break
                message = bus.recv(timeout=0.002)
                if message is None or message.is_extended_id or message.arbitration_id not in FRAME_IDS:
                    continue
                if len(message.data) != 8:
                    report['errors'].append('Unexpected CAN DLC')
                    continue
                report['rx_frames'] += 1
                frames[message.arbitration_id] = bytes(message.data)
                if len(frames) != 6:
                    continue
                row = decode_snapshot(frames)
                row['host_monotonic_s'] = now
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
                stream.flush()
                report['snapshots'] += 1
                report['fault_snapshots'] += int(row['fault'] != 0)
                frames = {}
                if row['phase_enabled'] or row['state'] == 2:
                    report['motion_detected'] = True
                    report['motion_stop_action'] = 'heartbeat_released_for_firmware_link_loss'
                    stop_deadline = now + 0.30
        report['completed'] = True
    except Exception as exc:
        report['errors'].append(str(exc))
        report['completed'] = False
    finally:
        bus.shutdown()
        report['duration_s'] = time.monotonic() - started
        (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='PCAN_USBBUS1')
    parser.add_argument('--output', required=True)
    parser.add_argument('--duration', type=float, default=10.0)
    parser.add_argument('--heartbeat-ms', type=float, default=20.0)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0 if report.get('completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
