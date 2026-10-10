"""Offline decoder for LOCKED thermal diagnostic CAN, never a training transport.

No hardware imports, writes, start commands, temperature synthesis or approvals.
Input is the raw JSONL format of the repository's listen-only can_monitor.py.
"""
import argparse
import json
import math
import os
from pathlib import Path
import struct
import zlib
import can_transport as wire

FIRMWARE = 'g431-speedloop-heat-can-v1'
PROTOCOL = 'motor-td3-thermal-diagnostic-v1'
CAN_ID = 0x626
SIZE = 144
LAYOUT = struct.Struct('<4sBBHQQIIHHQQQQQ3d3fQQIII')
UNKNOWN = 2**64-1
CALIBRATED, LIMITS, SEED, SAMPLE, WINDOW, ACCOUNTING, SAMPLE_FRESH, WINDOW_FRESH, LOCKED = (
    1, 2, 4, 8, 16, 32, 64, 128, 256)
FEED_FAULTS = ('none', 'init', 'calibration', 'thermal', 'adc', 'sequence', 'time', 'stale', 'peak')
THERMAL_FAULTS = ('none', 'config', 'boot_unknown', 'sensor', 'sequence', 'time', 'stale',
                  'current', 'budget', 'stall', 'duration')


class DiagnosticError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise DiagnosticError(reason)


def unpack(data):
    require(len(data) == SIZE and zlib.crc32(data[:-4]) == struct.unpack('<I', data[-4:])[0],
            'Thermal datagram size/CRC failure')
    (magic, version, reserved, size, nonce, boot, seq, flags, ff, gf, stamp,
     sample_seq, sample_time, window_seq, window_time, *tail) = LAYOUT.unpack(data[:-4])
    used, budgets = tail[:3], tail[3:6]
    energized, stalled, period, max_age, window_us = tail[6:]
    require((magic, version, reserved, size) == (b'THT1', 1, 0, SIZE), 'Unsupported thermal schema')
    require(nonce and boot and seq and stamp != UNKNOWN, 'Missing thermal session/sequence/time')
    require(flags & LOCKED and not flags & ~511, 'Missing locked flag or unknown flags')
    require(ff < len(FEED_FAULTS) and gf < len(THERMAL_FAULTS), 'Unknown thermal fault code')
    c, l, s, a, sample, window = (bool(flags & f) for f in (CALIBRATED, LIMITS, SEED, ACCOUNTING, SAMPLE, WINDOW))
    require((not l or c) and (not s or l) and a == (l and s), 'Inconsistent calibration/seed flags')
    require((not sample or a) and (not window or sample), 'Observation without known accounting')
    require((not flags & SAMPLE_FRESH or sample) and (not flags & WINDOW_FRESH or window),
            'Fresh flag without observation')
    if l:
        require(all(math.isfinite(v) and v > 0 for v in budgets), 'Invalid budget limits')
        require(period > 0 and window_us > 0 and window_us % period == 0, 'Invalid observation timing')
    else:
        require(all(math.isnan(v) for v in budgets) and not (period or max_age or window_us),
                'Unverified limits must be unknown')
    if a:
        require(all(math.isfinite(v) and v >= 0 for v in used) and
                0 <= stalled <= energized < UNKNOWN, 'Invalid accounting numbers')
    else:
        require(all(math.isnan(v) for v in used) and energized == stalled == UNKNOWN,
                'Unknown warm state must not look cold')
    if sample:
        require(sample_seq > 0 and sample_time <= stamp, 'Invalid sample sequence/time')
        require(bool(flags & SAMPLE_FRESH) == (stamp-sample_time <= period+max_age),
                'Incorrect sample freshness')
    else:
        require(sample_seq == 0 and sample_time == UNKNOWN, 'Invalid absent sample')
    if window:
        require(window_seq > 0 and window_time <= sample_time and
                window_seq <= sample_seq // (window_us // period), 'Invalid window sequence/time')
        require(bool(flags & WINDOW_FRESH) == (stamp-window_time <= window_us+max_age),
                'Incorrect window freshness')
    else:
        require(window_seq == 0 and window_time == UNKNOWN, 'Invalid absent window')
    reasons = []
    if not c: reasons.append('电流增益未标定')
    if not l: reasons.append('热保护边界未验证')
    if not s: reasons.append('初始热状态未知')
    if not sample: reasons.append('没有有效的校准电流采样')
    elif not flags & SAMPLE_FRESH: reasons.append('电流采样已过期')
    if not window: reasons.append('尚无完整热预算窗口')
    elif not flags & WINDOW_FRESH: reasons.append('热预算窗口已过期')
    if ff: reasons.append('采样接入故障：'+FEED_FAULTS[ff])
    if gf: reasons.append('热保护故障：'+THERMAL_FAULTS[gf])
    loads = [u/b for u, b in zip(used, budgets)] if a else [None]*3
    require(not a or all(math.isfinite(v) for v in loads), 'Unrepresentable budget ratio')
    if a and any(v >= 1 for v in loads): reasons.append('至少一相热预算已耗尽')
    return dict(protocol_id=PROTOCOL, nonce=f'{nonce:016x}', boot_id=f'{boot:016x}',
                snapshot_seq=seq, capture_us=stamp, flags=flags,
                calibrated=c, limits_verified=l, initial_heat_known=s,
                sample_seq=sample_seq, sample_capture_us=sample_time if sample else None,
                window_seq=window_seq, window_end_us=window_time if window else None,
                sample_fresh_at_capture=bool(flags & SAMPLE_FRESH),
                window_fresh_at_capture=bool(flags & WINDOW_FRESH),
                used_a2s=used if a else [None]*3, budget_a2s=budgets if l else [None]*3,
                phase_load=loads, energized_us=energized if a else None,
                stalled_us=stalled if a else None, sample_period_us=period or None,
                max_age_us=max_age if l else None, window_us=window_us or None,
                feed_fault_code=ff, feed_fault=FEED_FAULTS[ff],
                thermal_fault_code=gf, thermal_fault=THERMAL_FAULTS[gf],
                block_reasons=reasons, motion_inhibited=True, motion_approved=False,
                training_telemetry=False, temperature_c=None)


class Reassembler:
    def __init__(self):
        self.pending = None
        self.last_time = 0.0

    def check_timeout(self, now):
        if not math.isfinite(now) or now < self.last_time or (self.pending is not None and now-self.started >= .05):
            self.pending = None
            raise DiagnosticError('Thermal fragment timeout/clock reversal')
        self.last_time = now

    def feed(self, frame, now):
        self.check_timeout(now)
        try:
            require(len(frame) == 8 and frame[0] == 0xD1 and frame[3] == SIZE, 'Invalid thermal fragment')
            tag, index = frame[1:3]
            if self.pending is None:
                require(index == 0, 'Missing first thermal fragment')
                self.pending, self.started, self.tag, self.index = bytearray(), now, tag, 0
            require((tag, index) == (self.tag, self.index), 'Thermal fragment gap/reorder/overlap')
            self.pending.extend(frame[4:]); self.index += 1
            if len(self.pending) == SIZE:
                data, self.pending = bytes(self.pending), None
                return unpack(data)
        except (DiagnosticError, struct.error):
            self.pending = None
            raise
        return None


class Decoder:
    """One capture/session; boot changes require a separate explicitly audited log."""
    def __init__(self):
        self.hello_rx, self.heat_rx = wire.Reassembler(), Reassembler()
        self.session, self.previous, self.last_time = None, None, 0.0

    def feed(self, row):
        now = row['host_monotonic_s']
        require(type(now) in (float, int) and math.isfinite(now) and now >= self.last_time,
                'Invalid host observation clock')
        self.last_time = now
        self.heat_rx.check_timeout(now)
        self.hello_rx.check_timeout(now)
        require(not row.get('error') and not row.get('status_frame'), 'CAN error/status event in capture')
        identifier = row['arbitration_id']
        if identifier not in (wire.RESPONSE_ID, CAN_ID):
            return None
        require(all(row.get(k) is False for k in ('extended', 'remote', 'error', 'status_frame', 'fd')) and
                row['dlc'] == 8, 'Expected standard classic CAN data frame')
        frame = bytes.fromhex(row['data_hex'])
        require(len(frame) == 8, 'Invalid raw CAN length')
        if identifier == wire.RESPONSE_ID:
            data = self.hello_rx.feed(frame, now)
            if data is None: return None
            obj, meta = wire.unpack(data)
            require(obj['type'] == 'hello' and obj.get('firmware_id') == FIRMWARE and
                    obj.get('profile_id') == FIRMWARE and obj.get('capabilities') == [],
                    'Thermal diagnostics require exact zero-capability HELLO identity')
            require(self.session is None, 'Repeated HELLO or session/boot change')
            self.session = (f"{meta['nonce']:016x}", f"{meta['boot']:016x}")
            return None
        require(self.session is not None, 'Thermal packet arrived before validated HELLO')
        obj = self.heat_rx.feed(frame, now)
        if obj is None: return None
        require((obj['nonce'], obj['boot_id']) == self.session, 'Thermal packet from wrong session/boot')
        if self.previous:
            p = self.previous
            require(obj['snapshot_seq'] > p['snapshot_seq'] and obj['capture_us'] >= p['capture_us'],
                    'Replayed thermal snapshot or device clock reversal')
            require((obj['flags'] & 7) == (p['flags'] & 7) and obj['budget_a2s'] == p['budget_a2s'] and
                    (obj['sample_period_us'], obj['max_age_us'], obj['window_us']) ==
                    (p['sample_period_us'], p['max_age_us'], p['window_us']), 'Configuration changed during boot')
            require(obj['sample_seq'] >= p['sample_seq'] and obj['window_seq'] >= p['window_seq'],
                    'Observation counters decreased')
            for count, timestamp, step in (('sample_seq','sample_capture_us','sample_period_us'),
                                          ('window_seq','window_end_us','window_us')):
                if p[timestamp] is not None:
                    require(obj[timestamp] == p[timestamp]+(obj[count]-p[count])*p[step],
                            'Observation timestamps inconsistent with counters')
            if obj['initial_heat_known']:
                require(all(u >= v for u, v in zip(obj['used_a2s'], p['used_a2s'])) and
                        obj['energized_us'] >= p['energized_us'] and obj['stalled_us'] >= p['stalled_us'],
                        'Heat accounting decreased without validated cooling')
            require((not p['feed_fault_code'] or obj['feed_fault_code'] == p['feed_fault_code']) and
                    (not p['thermal_fault_code'] or obj['thermal_fault_code'] == p['thermal_fault_code']),
                    'Latched fault was cleared/changed')
            require(obj['snapshot_seq'] == p['snapshot_seq']+1, 'Missing complete thermal snapshot')
        obj['host_monotonic_s'] = now
        obj['assembly_elapsed_us'] = round((now-self.heat_rx.started)*1e6)
        self.previous = obj
        return obj


def audit(rows):
    decoder, snapshots, errors = Decoder(), [], []
    for line, row in enumerate(rows, 1):
        try:
            obj = decoder.feed(row)
            if obj is not None: snapshots.append(obj)
        except (DiagnosticError, wire.WireError, KeyError, TypeError, ValueError, struct.error) as exc:
            errors.append(dict(line=line, reason=str(exc)[:240]))
    if decoder.heat_rx.pending is not None or decoder.hello_rx.pending is not None:
        errors.append(dict(line=None, reason='Truncated final datagram'))
    if not snapshots:
        errors.append(dict(line=None, reason='No validated complete thermal snapshot'))
    counts = {}
    for s in snapshots:
        key = s['feed_fault']+'/'+s['thermal_fault']
        counts[key] = counts.get(key, 0)+1
    return dict(schema_version=1, scope='offline locked thermal CAN diagnostic audit',
                passed=not errors, snapshots=len(snapshots), errors=errors, fault_counts=counts,
                latest=snapshots[-1] if snapshots else None,
                hardware_accessed=False, live_freshness_verified=False,
                motion_approved=False, training_telemetry=False, thermal_protection_verified=False), snapshots


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', required=True); p.add_argument('--output', required=True)
    args = p.parse_args(); out = Path(args.output).resolve(); source = Path(args.log).resolve()
    if os.name == 'nt' and Path(r'E:\simulink\_codex_tmp').resolve() not in out.parents:
        raise ValueError('Windows audit output must be under the approved temp root')
    if source == out or out in source.parents or (out.exists() and any(out.iterdir())):
        raise ValueError('Use a fresh output directory separate from the raw log')
    rows = [json.loads(line) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    summary, snapshots = audit(rows); out.mkdir(parents=True, exist_ok=True)
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (out/'snapshots.jsonl').write_text(''.join(json.dumps(s, ensure_ascii=False, allow_nan=False)+'\n' for s in snapshots), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    if not summary['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
