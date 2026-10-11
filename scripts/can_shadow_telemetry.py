#!/usr/bin/env python3
"""Read-only CAN telemetry session for a motion-inhibited TD3 endpoint.

This entry point sends only the protocol HELLO datagram.  It never sends
BEGIN, GAINS, or STOP, so it cannot start motion or change controller gains.
The endpoint must therefore be a diagnostic/shadow firmware that publishes
telemetry after HELLO.  Records are observations only and are not TD3 replay
experiences because no action was applied.
"""
import argparse
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                        'skills/motor-td3-serial-tuning/scripts'))
from can_transport import PcanLink, Reassembler, WireError, fragment, pack, unpack


def hello_frames(profile_id, nonce, transfer=0):
    return fragment(pack({'type': 'hello', 'profile_id': profile_id}, nonce), transfer)


def receive_packet(link, reassembler, deadline):
    while time.monotonic() < deadline:
        frame = link.receive()
        if frame is None:
            continue
        packet = reassembler.feed(frame, time.monotonic())
        if packet is not None:
            return unpack(packet)
    return None


def run(args):
    if not args.allow_live:
        raise ValueError('Shadow CAN access requires explicit --allow-live')
    if args.duration < 0 or args.duration != args.duration:
        raise ValueError('duration must be finite and nonnegative')
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new and empty')
    output.mkdir(parents=True, exist_ok=True)
    nonce = secrets.randbits(64) or 1
    report = {
        'schema_version': 1,
        'mode': 'can-shadow-telemetry',
        'profile_id': args.profile_id,
        'transport': 'PCAN classic CAN',
        'bitrate': 500000,
        'observation_only': True,
        'motion_commands_sent': 0,
        'gain_commands_sent': 0,
        'td3_trainable_transitions': 0,
        'telemetry_records': 0,
        'rx_frames': 0,
        'errors': [],
    }
    link = None
    rows_path = output / 'telemetry.jsonl'
    try:
        link = PcanLink(args.channel)
        transfer = 0
        for frame in hello_frames(args.profile_id, nonce, transfer):
            link.send(frame)
        reply = receive_packet(link, Reassembler(), time.monotonic() + args.hello_timeout)
        if reply is None:
            raise WireError('No HELLO reply; endpoint may be baseline firmware or powered off')
        hello, meta = reply
        if hello.get('type') != 'hello' or meta.get('nonce') != nonce:
            raise WireError('HELLO identity/nonce mismatch')
        report['hello'] = hello
        report['boot_id'] = hello.get('boot_id')
        reassembler = Reassembler()
        deadline = time.monotonic() + args.duration
        with rows_path.open('x', encoding='utf-8') as stream:
            while time.monotonic() < deadline:
                frame = link.receive()
                if frame is None:
                    continue
                report['rx_frames'] += 1
                packet = reassembler.feed(frame, time.monotonic())
                if packet is None:
                    continue
                obj, packet_meta = unpack(packet)
                if obj.get('type') != 'telemetry':
                    continue
                if obj.get('boot_id') != report['boot_id']:
                    raise WireError('Telemetry boot identity changed')
                stream.write(json.dumps({'meta': packet_meta, 'telemetry': obj},
                                        separators=(',', ':')) + '\n')
                stream.flush()
                report['telemetry_records'] += 1
        report['completed'] = True
    except Exception as exc:
        report['errors'].append(str(exc))
        report['completed'] = False
    finally:
        if link is not None:
            link.close()
        (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='PCAN_USBBUS1')
    parser.add_argument('--profile-id', default='g431-speedloop-diag-v1')
    parser.add_argument('--output', required=True)
    parser.add_argument('--duration', type=float, default=10.0)
    parser.add_argument('--hello-timeout', type=float, default=1.0)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except (ValueError, OSError, WireError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0 if report.get('completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
