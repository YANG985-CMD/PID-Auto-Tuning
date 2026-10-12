"""Nonblocking, latest-only MATLAB suggestions. Cannot send any device command."""
import hashlib
import json
import math
from pathlib import Path
import queue
import socket
import struct
import threading
import time

CHECKPOINT_SHA = '2d9516d757ad8e9784da9171afe48f5dc60f809666639084c691bbc10b23efab'
POLICY = 'experimental-shadow-20261012-kp-only'
FIRMWARE = 'g431-speedloop-pi-motion-v5'
SCALES = [1000, 1000, 1000, 1000, 3, 2, 24, .003389, .00144, 3000]
DEADLINE_SECONDS = .045


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def validate_reply(reply, request):
    """Bind suggestion to exact source and independently recompute the mapping."""
    if not reply.get('ok') or reply.get('request_id') != request['request_id']:
        raise ValueError('MATLAB rejected request or reply identity mismatch')
    r = reply['result']
    if (r.get('policy_version') != POLICY or r.get('checkpoint_sha256') != CHECKPOINT_SHA or
            r.get('shadow_only') is not True or r.get('hardware_writeback') is not False or
            r.get('training_performed') is not False):
        raise ValueError('Unreviewed policy or writeback capability')
    if request['op'] == 'hello':
        if r['state_scale'] != SCALES: raise ValueError('Normalization mismatch')
        return r
    t = request['telemetry']
    if (r.get('telemetry_seq') != t['seq'] or r.get('t_us') != t['t_us'] or
            r.get('boot_id') != t['boot_id'] or r.get('ki_masked') is not True or
            r.get('deployment_allowed') is not False):
        raise ValueError('Stale/cross-session response or missing Ki mask')
    raw = [t['speed_ref'], t['speed'], t['speed_ref']-t['speed'], t['error_history'],
           t['integral_output'], t['current'], t['vbus'], t['kp'], t['ki'], t['elapsed_ms']]
    obs = [f32(max(-5, min(5, x/s))) for x, s in zip(raw, SCALES)]
    if r['raw_state'] != raw or r['observation'] != obs:
        raise ValueError('State or normalization changed in transit')
    actions = r['raw_action']
    if len(actions) != 2 or not all(math.isfinite(x) and abs(x) <= 1 for x in actions):
        raise ValueError('Invalid action')
    mapped = []
    for current, action, lower, upper, step in zip(
            [t['kp'], t['ki']], actions, [.0013556, .00072], [.0054224, .00216], [.00027112, .000144]):
        current = f32(current)
        if not lower <= current <= upper: raise ValueError('Source gain outside protocol envelope')
        distance = min(upper, current+step)-current if action >= 0 else current-max(lower, current-step)
        mapped.append(f32(current + distance*action))
    if (r['original_two_head_gains'] != mapped or r['kp'] != mapped[0] or
            r['ki'] != f32(.00144) or not math.isfinite(r['inference_ms']) or r['inference_ms'] < 0):
        raise ValueError('Gain mapping mismatch')
    return r


class ShadowClient:
    """All network waits stay on the worker, never on the CAN/STOP thread."""
    def __init__(self, port, token_file):
        self.port = port
        self.token = Path(token_file).read_text(encoding='ascii').strip()
        if len(self.token) < 64: raise ValueError('Private token too short')
        self.pending = queue.Queue(maxsize=1)
        self.completed = queue.Queue(maxsize=512)
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.error = None
        self.submitted = self.replaced = self.records_dropped = 0
        self.worker = threading.Thread(target=self._run, daemon=True, name='MATLAB-shadow')
        self.worker.start()

    def _record(self, value):
        try: self.completed.put_nowait(value)
        except queue.Full: self.records_dropped += 1

    def submit(self, telemetry, received_at=None, source='live_motor'):
        item = (dict(telemetry), time.perf_counter() if received_at is None else received_at, source)
        self.submitted += 1
        try: self.pending.put_nowait(item)
        except queue.Full:
            try: self.pending.get_nowait(); self.replaced += 1
            except queue.Empty: pass
            try: self.pending.put_nowait(item)
            except queue.Full: self.replaced += 1

    def drain(self):
        records = []
        while True:
            try: records.append(self.completed.get_nowait())
            except queue.Empty: return records

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=.6)
        return not self.worker.is_alive()

    def _run(self):
        request_id = 0
        try:
            with socket.create_connection(('127.0.0.1', self.port), timeout=.2) as sock:
                sock.settimeout(.2)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                buffered = b''
                def call(op, **fields):
                    nonlocal request_id, buffered
                    request_id += 1
                    request = dict(schema_version=1, request_id=request_id, op=op, token=self.token,
                                   shadow_only=True, hardware_writeback=False, **fields)
                    sock.sendall(json.dumps(request, allow_nan=False).encode('ascii')+b'\n')
                    while b'\n' not in buffered:
                        block = sock.recv(4096)
                        if not block: raise ConnectionError('MATLAB disconnected')
                        buffered += block
                        if len(buffered)>16384: raise ValueError('Oversized reply')
                    line, buffered = buffered.split(b'\n', 1)
                    return validate_reply(json.loads(line), request)
                call('hello')
                self.ready.set()
                while not self.stopping.is_set():
                    try: t, received, source = self.pending.get(timeout=.02)
                    except queue.Empty: continue
                    started = time.perf_counter()
                    record = dict(source=source, telemetry_seq=t['seq'], t_us=t['t_us'], boot_id=t['boot_id'],
                                  hardware_writeback=False, shadow_only=True, accepted=False)
                    if started-received >= DEADLINE_SECONDS:
                        record.update(rejection='source_stale_before_inference', source_age_ms=(started-received)*1000)
                        self._record(record); continue
                    result = call('predict', firmware_id=FIRMWARE, telemetry=t)
                    finished = time.perf_counter()
                    record.update(result=result, roundtrip_ms=(finished-started)*1000,
                                  source_age_ms=(finished-received)*1000)
                    record['accepted'] = finished-received < DEADLINE_SECONDS
                    if not record['accepted']: record['rejection'] = 'source_deadline_exceeded'
                    self._record(record)
        except Exception as exc:
            self.error = str(exc)
            self._record(dict(source='bridge', accepted=False, rejection='worker_failure', error=self.error,
                              hardware_writeback=False, shadow_only=True))

    def summary(self, records):
        replies = [r for r in records if 'result' in r]
        accepted = [r for r in replies if r['accepted']]
        def percentiles(key):
            values = sorted(r[key] for r in replies)
            if not values: return None
            return dict(p50=values[round((len(values)-1)*.5)],
                        p95=values[round((len(values)-1)*.95)], maximum=values[-1])
        return dict(policy_version=POLICY, checkpoint_sha256=CHECKPOINT_SHA, shadow_only=True,
                    hardware_writeback=False, td3_training_performed=False, submitted=self.submitted,
                    pending_replaced=self.replaced, records_dropped=self.records_dropped,
                    returned=len(replies), accepted=len(accepted), rejected=len(records)-len(accepted),
                    deadline_ms=DEADLINE_SECONDS*1000, roundtrip_ms=percentiles('roundtrip_ms'),
                    source_age_ms=percentiles('source_age_ms'), worker_error=self.error,
                    implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
