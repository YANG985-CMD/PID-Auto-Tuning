#!/usr/bin/env python3
"""Bounded HELLO-only capture for the audited, motion-inhibited SpeedLoop build.

Normal CAN mode supplies ACKs. No BEGIN, GAINS, STOP, reset, resume or memory
write is performed. After capture the known locked core is halted before
releasing the adapter. The operator prepares a unique debugger boot token with
24V disconnected, verifies the locked image, then confirms board power.
Diagnostics are separate, non-atomic observations; never TD3 experiences.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import struct
import subprocess
import time

import can_transport as wire

IDENTITY = 'g431-speedloop-diag-v1'
AUDITED_BIN_SHA = '90195b9a9e1d06400592e8aac5f31b167eab0fad095ad54ddb361d0f849022a6'
IMAGE_BYTES = 32832
REGISTERS = {'tim1_cr1': 0x40012C00, 'tim1_ccer': 0x40012C20,
             'tim1_bdtr': 0x40012C44, 'debug_id': 0xE0042000}
RAM_NAMES = ('endpoint_ready', 'initialized', 'irq_fault', 'Motor_state',
             'motor_td3_g431_debugger_boot_token')


def validate_manifest(manifest):
    if (manifest.get('firmware_id') != IDENTITY or manifest.get('capabilities') != 0
            or manifest.get('bin_sha256') != AUDITED_BIN_SHA
            or manifest.get('image_bytes') != IMAGE_BYTES
            or manifest.get('motion_enable_implemented') is not False
            or manifest.get('gain_application_implemented') is not False
            or manifest.get('forbidden_motion_symbols_absent') is not True):
        raise wire.WireError('Expected the audited motion-inhibited SpeedLoop image')
    for name in RAM_NAMES:
        address = manifest['symbols'][name]
        if not isinstance(address, int) or not 0x20000000 <= address < 0x20008000 - 8:
            raise wire.WireError('Invalid manifest RAM address')


def parse_preflight(text, manifest, state='Running'):
    found = {}
    for name, address in {**REGISTERS, **{n: manifest['symbols'][n] for n in RAM_NAMES}}.items():
        width = 2 if name == 'Motor_state' else 8
        match = re.search(rf'(?im)^{address:08x}:\s+([0-9a-f]{{{width}}})\b', text)
        if not match:
            raise wire.WireError('Missing board preflight read: ' + name)
        found[name] = int(match.group(1), 16)
    # The high half is explicitly read and must also be zero after consumption.
    token = manifest['symbols']['motor_td3_g431_debugger_boot_token'] + 4
    match = re.search(rf'(?im)^{token:08x}:\s+([0-9a-f]{{8}})\b', text)
    if not match or int(match.group(1), 16):
        raise wire.WireError('Debugger boot token was not consumed')
    if (not re.search(rf'Core 0 .*:\s+{state}\b', text)
            or found['debug_id'] & 0xFFF != 0x468
            or found['tim1_cr1'] & 1 or found['tim1_ccer'] != 0
            or found['tim1_bdtr'] & 0x8000 or found['Motor_state'] != 0
            or found['endpoint_ready'] != 1 or found['initialized'] != 1
            or found['irq_fault'] != 0 or found['motor_td3_g431_debugger_boot_token'] != 0):
        raise wire.WireError('Board state/fault/readiness or disabled TIM1 check failed')
    return found


def read_commands(manifest):
    commands = ['st']
    for address in REGISTERS.values():
        commands.append(f'read32 0x{address:08x} 4')
    for name in RAM_NAMES:
        commands.append(f'{"read8" if name == "Motor_state" else "read32"} '
                        f'0x{manifest["symbols"][name]:08x} {1 if name == "Motor_state" else 4}')
    commands.append(f'read32 0x{manifest["symbols"][RAM_NAMES[-1]]+4:08x} 4')
    return commands


def debug_read(args, commands, output, name):
    cmd = [args.pyocd, 'commander', '--no-config', '-t', 'cortex_m', '-u', args.uid,
           '-W', '-M', 'attach']
    for command in commands:
        cmd += ['-c', command]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    (output / name).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise wire.WireError('Debug state read failed')
    return result.stdout


def preflight(args, manifest, output):
    """Attach without halt/reset. Verify the complete Flash image and current RAM."""
    flash = output / 'preflight-flash-private.bin'
    commands = [f'savemem 0x08000000 {manifest["image_bytes"]} {flash.as_posix()}'] + read_commands(manifest)
    text = debug_read(args, commands, output, 'preflight-debug.txt')
    if not flash.exists():
        raise wire.WireError('Debug preflight failed; no CAN request sent')
    if hashlib.sha256(flash.read_bytes()).hexdigest() != AUDITED_BIN_SHA:
        raise wire.WireError('Flash differs from the audited locked image; no CAN request sent')
    return parse_preflight(text, manifest)


def hold_board(args, manifest, output):
    # This is appropriate only for this whole-image-verified firmware: TIM1
    # never runs and every SysTick disables outputs. Halt is not a motor stop
    # for a general FOC image. Keep PCAN supplying ACKs until halt/readback.
    text = debug_read(args, ['halt'] + read_commands(manifest), output, 'final-debug.txt')
    return parse_preflight(text, manifest, state='Halted')


def finish(link, hold, report):
    """Always release CAN, but first retire the verified locked transmitter."""
    try:
        report['final_board_state'] = hold()
        report['core_halted_before_adapter_release'] = True
    except Exception as exc:
        report['hold_error'] = str(exc)
        report['verified'] = False
    finally:
        try:
            link.close()
            report['adapter_released'] = True
        except Exception as exc:
            report['close_error'] = str(exc)
            report['verified'] = False


def decode_diag(identifier, data):
    if len(data) != 8 or identifier not in range(0x622, 0x626):
        raise wire.WireError('Unexpected diagnostic ID/DLC')
    if identifier == 0x622:
        version, fault, flags, hall, reserved, age = struct.unpack('<BBHBBH', data)
        if version != 1 or reserved or flags & ~0x37 or hall > 7:
            raise wire.WireError('Invalid diagnostic status')
        return dict(guard_fault=fault, adc_calibrated=bool(flags & 1), hall_valid=bool(flags & 2),
                    outputs_enabled=bool(flags & 4), irq_fault=bool(flags & 16),
                    hall_bad=bool(flags & 32), hall_code=hall, adc_age_ms=age)
    names = {0x623: ('stored_kp', 'stored_ki'), 0x624: ('nominal_vbus_v', 'nominal_current_a'),
             0x625: ('hall_speed_rpm', 'pi_integral_output')}[identifier]
    values = struct.unpack('<ff', data)
    if not all(math.isfinite(v) for v in values):
        raise wire.WireError('Non-finite diagnostic observation')
    return dict(zip(names, values))


class Collector:
    """No learning, command application, retry or automatic rearming path."""
    def __init__(self, nonce, boot, write_row):
        self.nonce, self.boot, self.write_row = nonce, boot, write_row
        self.rx = wire.Reassembler()
        self.hello = None
        self.expected = 0x622
        self.counts = Counter()
        self.ranges = {}
        self.last_status = None
        self.status_times = []
        self.cycles = 0

    def feed(self, identifier, data, host_s, adapter_us):
        self.write_row(dict(host_monotonic_s=host_s, adapter_timestamp_us=adapter_us,
                            arbitration_id=f'0x{identifier:03X}', data_hex=data.hex()))
        self.counts[f'0x{identifier:03X}'] += 1
        if identifier == wire.RESPONSE_ID:
            if self.hello is not None:
                raise wire.WireError('Unexpected protocol packet after HELLO')
            packet = self.rx.feed(data, host_s)
            if packet:
                obj, meta = wire.unpack(packet)
                if (obj.get('type') != 'hello' or obj.get('firmware_id') != IDENTITY
                        or obj.get('profile_id') != IDENTITY or obj.get('capabilities') != []
                        or meta['nonce'] != self.nonce or meta['boot'] != self.boot):
                    raise wire.WireError('HELLO identity/session/capability mismatch')
                self.hello = obj
            return
        if self.hello is None:
            raise wire.WireError('Diagnostic received before verified HELLO')
        if identifier != self.expected:
            raise wire.WireError('Diagnostic frame gap/reorder/unknown ID')
        fields = decode_diag(identifier, data)
        if identifier == 0x622:
            if (fields['guard_fault'] != 12 or not fields['adc_calibrated']
                    or fields['outputs_enabled'] or fields['irq_fault'] or fields['hall_bad']
                    or fields['adc_age_ms'] > 30
                    or fields['hall_valid'] != (1 <= fields['hall_code'] <= 6)):
                raise wire.WireError('Locked firmware status/ADC freshness check failed')
            self.last_status = host_s
            self.status_times.append(host_s)
        for name, value in fields.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lo, hi = self.ranges.get(name, (value, value))
                self.ranges[name] = (min(lo, value), max(hi, value))
        self.write_row(dict(type='raw_diagnostic', arbitration_id=f'0x{identifier:03X}',
                            fields=fields, host_monotonic_s=host_s, td3_experience=False))
        self.expected = 0x622 if identifier == 0x625 else identifier + 1
        self.cycles += int(identifier == 0x625)

    def check_freshness(self, now, started):
        if self.hello is None:
            self.rx.check_timeout(now)
            if now - started > 1:
                raise wire.WireError('HELLO timeout; automatic retry is prohibited')
        elif now - (self.last_status if self.last_status is not None else started) > .5:
            raise wire.WireError('Diagnostic stream timeout')

    def summary(self):
        gaps = [b-a for a, b in zip(self.status_times, self.status_times[1:])]
        return dict(hello=self.hello, frame_counts=dict(self.counts), complete_cycles=self.cycles,
                    partial_cycle_at_end=self.expected != 0x622, ranges=self.ranges,
                    max_status_gap_s=max(gaps) if gaps else None)


def capture(link, collector, duration, clock=time.monotonic, sleep=time.sleep):
    """Exactly one datagram. Each fragment only reads back adapter normal mode."""
    packet = wire.pack(dict(type='hello', profile_id=IDENTITY), collector.nonce)
    frames = wire.fragment(packet, 1)
    started = clock()
    deadline = started + duration
    for frame in frames:
        if clock() - started >= wire.FRAGMENT_TIMEOUT:
            raise wire.WireError('Host HELLO fragment budget exceeded')
        link.send(frame)
        sleep(.0005)
    while clock() < deadline:
        collector.check_freshness(clock(), started)
        link.mode()
        status, message, stamp = link.api.Read(link.handle)
        if link.value(status) == link.value(link.basic.PCAN_ERROR_QRCVEMPTY):
            sleep(.001)
            continue
        link.check(status)
        if (link.value(message.MSGTYPE) != link.value(link.basic.PCAN_MESSAGE_STANDARD)
                or link.value(message.LEN) != 8):
            raise wire.WireError('Unexpected remote/extended/error/status/short frame')
        adapter_us = (link.value(stamp.micros) + 1000*link.value(stamp.millis)
                      + 1000*(1 << 32)*link.value(stamp.millis_overflow))
        collector.feed(link.value(message.ID), bytes(message.DATA[:8]), clock(), adapter_us)
    if collector.hello is None or collector.cycles < 3:
        raise wire.WireError('Insufficient verified diagnostic stream')
    return dict(duration_s=clock()-started, hello_requests=1, tx_frames=len(frames))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--pyocd', required=True)
    p.add_argument('--uid', required=True)
    p.add_argument('--boot', required=True, type=lambda s: int(s, 16))
    p.add_argument('--channel', default='PCAN_USBBUS1')
    p.add_argument('--duration', type=float, default=3)
    p.add_argument('--output', required=True)
    p.add_argument('--allow-live', action='store_true')
    p.add_argument('--board-power-confirmed', action='store_true')
    args = p.parse_args()
    if (not args.allow_live or not args.board_power_confirmed or not 0 < args.boot < 2**64
            or not math.isfinite(args.duration) or not 1 <= args.duration <= 5):
        p.error('Requires live/power acknowledgement, prepared boot token and 1..5 seconds')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema_version=1, mode='speedloop-hello-only-diagnostic',
                  utc=datetime.now(timezone.utc).isoformat(), verified=False,
                  channel=args.channel, bitrate=500000, normal_mode_required=True,
                  motor_start_requested=False, gains_written=False, td3_experiences=0,
                  temperature_available=False, atomic_diagnostic_snapshot=False,
                  firmware_bin_sha256=AUDITED_BIN_SHA)
    link = None
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
        validate_manifest(manifest)
        with (output / 'capture.jsonl').open('x', encoding='utf-8') as log:
            collector = Collector(secrets.randbits(64) or 1, args.boot,
                                  lambda row: log.write(json.dumps(row, allow_nan=False) + '\n'))
            link = wire.PcanLink(args.channel)
            report['normal_mode_verified'] = True
            # The only transmitted datagram is gated by a fresh whole-image and
            # board register check. No per-fragment MCU halt disrupts the packet.
            report['preflight'] = preflight(args, manifest, output)
            report.update(capture(link, collector, args.duration))
            report['verified'] = True
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc)
    finally:
        if 'collector' in locals():
            report.update(collector.summary())
        if link is not None:
            if 'preflight' in report:
                finish(link, lambda: hold_board(args, manifest, output), report)
            else:
                # A mismatched/unsafe board must not be halted automatically.
                try:
                    link.close()
                    report['adapter_released'] = True
                except Exception as exc:
                    report['close_error'] = str(exc)
                    report['verified'] = False
        (output / 'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(report, allow_nan=False))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
