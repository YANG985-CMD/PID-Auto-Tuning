#!/usr/bin/env python3
"""Persistent loopback bridge. Mock by default; never use the mock profile on hardware."""
import argparse
import collections
import copy
import json
import math
import secrets
import socket
import struct
import threading
import time
import uuid
import zlib
from pathlib import Path

from session_checks import (audit_rows, check_profile, check_transition, decode_json,
                            integer, load_json, nonfinite_paths, number)

FIELDS = ['speed_ref', 'speed', 'speed_error', 'error_history', 'integral_output',
          'current', 'vbus', 'kp', 'ki', 'elapsed_ms']
PROTOCOL = 'motor-td3-json-crc-v1'
MAX_LINE = 16384


class SafetyError(RuntimeError):
    pass


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def inward_f32(value, lo, hi):
    """Round toward a representable value inside the actual local gain bounds."""
    value = f32(value)
    bits = struct.unpack('<I',struct.pack('<f',value))[0]
    if value > hi:
        value = struct.unpack('<f',struct.pack('<I',bits-1))[0]
    elif value < lo:
        value = struct.unpack('<f',struct.pack('<I',bits+1))[0]
    if not lo <= value <= hi:
        raise SafetyError('Gain interval has no compatible float32 value')
    return value


def encode_frame(obj):
    payload = json.dumps(obj, allow_nan=False, separators=(',', ':')).encode('ascii')
    return payload + b'*' + ('%08x' % zlib.crc32(payload)).encode('ascii') + b'\n'


def decode_frame(line):
    if len(line) > MAX_LINE or not line.endswith(b'\n'):
        raise SafetyError('Invalid frame length/terminator')
    try:
        payload, crc = line.rstrip(b'\r\n').rsplit(b'*', 1)
        if len(crc) != 8 or int(crc, 16) != zlib.crc32(payload):
            raise ValueError('CRC mismatch')
        obj = decode_json(payload.decode('ascii'))
        if not isinstance(obj, dict) or nonfinite_paths(obj):
            raise ValueError('Non-finite/non-object frame')
        return obj
    except (ValueError, UnicodeError) as exc:
        raise SafetyError(str(exc)) from exc


def validate_runtime(p, live=False):
    errors, _ = check_profile(p, live=True)
    if errors:
        raise SafetyError('; '.join(errors))
    if p['training'].get('state_fields') != FIELDS:
        errors.append('This runtime requires the documented ten state fields in order')
    r = p.get('runtime', {})
    if p['device'].get('protocol_id') != PROTOCOL:
        errors.append('Unsupported firmware protocol; legacy P1/P3 commands are not supported')
    scales = r.get('state_scale', [])
    if len(scales) != 10 or not all(number(x) and x > 0 for x in scales):
        errors.append('runtime.state_scale requires ten positive physical scales')
    if not integer(r.get('max_steps'), 1):
        errors.append('runtime.max_steps must be a positive integer')
    window = r.get('window_ms')
    s = p['safety']
    if not number(window) or not s['decision_window_min_ms'] <= window <= s['decision_window_max_ms']:
        errors.append('Invalid response window')
    refs = r.get('speed_refs_rpm', [])
    if not refs or not all(number(x) and abs(x) < s['speed_limit_rpm'] for x in refs):
        errors.append('Predefined speed reference plan is required')
    if c := p.get('controller'):
        for g in ('kp','ki'):
            if not c[g + '_min'] <= f32(c[g + '_baseline']) <= c[g + '_max']:
                errors.append('Float32 baseline outside bounds')
    if number(window) and window + s['max_apply_latency_ms'] >= s['max_trial_seconds'] * 1000:
        errors.append('Trial must cover one complete command and response')
    if live and (p.get('simulation_only') is not False or p['device']['port'] == 'MOCK_ONLY'):
        errors.append('Simulation profile cannot authorize a serial session')
    if live and p['mode'] not in {'train-live', 'evaluate'}:
        errors.append('Live bridge requires train-live/evaluate mode')
    if not live and p.get('simulation_only') is not True:
        errors.append('Mock requires an explicitly simulation-only profile')
    if errors:
        raise SafetyError('; '.join(errors))


def map_action(action, state, p):
    if not isinstance(action, list) or len(action) != 2 or not all(number(x) and -1 <= x <= 1 for x in action):
        raise SafetyError('Action must be two finite values in [-1,1]')
    out = {}
    for name, a in zip(('kp', 'ki'), action):
        c = p['controller']
        current = state[name]
        lo = max(c[name + '_min'], current - c['max_' + name + '_step'])
        hi = min(c[name + '_max'], current + c['max_' + name + '_step'])
        out[name] = inward_f32(current + (hi - current) * a if a >= 0 else current + (current - lo) * a, lo, hi)
        if not c[name + '_min'] <= out[name] <= c[name + '_max']:
            raise SafetyError('Float32 gain is outside bounds')
    return out


def observation(state, p):
    return [max(-5.0, min(5.0, state[k] / scale))
            for k, scale in zip(FIELDS, p['runtime']['state_scale'])]


def telemetry_check(f, p):
    for k in ('seq', 't_us', 't_apply_us', 'applied_seq', 'fault'):
        if not integer(f.get(k)):
            raise SafetyError('Missing/invalid telemetry field ' + k)
    for k in ('speed_ref', 'speed', 'error_history', 'integral_output', 'current',
              'vbus', 'temperature_c', 'kp', 'ki', 'elapsed_ms'):
        if not number(f.get(k)):
            raise SafetyError('Missing/non-finite telemetry field ' + k)
    if type(f.get('enabled')) is not bool:
        raise SafetyError('Missing enabled feedback')
    s, c = p['safety'], p['controller']
    if f['fault'] or abs(f['current']) >= s['current_limit_a'] or abs(f['speed']) >= s['speed_limit_rpm']:
        raise SafetyError('Device fault, overcurrent or overspeed')
    if not s['vbus_min_v'] <= f['vbus'] <= s['vbus_max_v']:
        raise SafetyError('Bus voltage outside limits')
    if s['thermal_protection'] == 'measured' and f['temperature_c'] >= s['temperature_limit_c']:
        raise SafetyError('Overtemperature')
    for g in ('kp', 'ki'):
        if not c[g + '_min'] <= f[g] <= c[g + '_max']:
            raise SafetyError('Telemetry gain outside limits')


def state_from(f):
    return {k: f['speed_ref'] - f['speed'] if k == 'speed_error' else f[k] for k in FIELDS}


class MockDevice:
    """Deterministic speed/current plant plus a wall-clock firmware lease model."""
    def __init__(self, p):
        self.p = p
        self.lock = threading.RLock()
        self.seq = self.t = self.applied = 0
        self.enabled = False
        self.fault = 0
        self.deadline = 0
        self.reset(1, p['runtime']['speed_refs_rpm'][0])
        self.stop()

    def reset(self, seed, ref):
        with self.lock:
            if self.fault:
                raise SafetyError('Firmware fault is latched')
            self.seed, self.ref = seed, ref
            self.speed = self.integral = self.current = self.previous_error = 0.0
            self.elapsed = 0
            self.kp = f32(self.p['controller']['kp_baseline'])
            self.ki = f32(self.p['controller']['ki_baseline'])
            self.enabled = True
            self.deadline = time.monotonic() + self.p['safety']['action_lease_ms'] / 1000
            return self.frame()

    def frame(self):
        with self.lock:
            if self.enabled and time.monotonic() >= self.deadline:
                self.enabled, self.fault = False, 9
            return dict(seq=self.seq, t_us=self.t, t_apply_us=getattr(self, 'apply_t', self.t),
                        applied_seq=self.applied, fault=self.fault, enabled=self.enabled,
                        speed_ref=self.ref, speed=self.speed, error_history=self.previous_error,
                        integral_output=self.integral, current=self.current, vbus=24.0,
                        temperature_c=30.0, kp=self.kp, ki=self.ki, elapsed_ms=self.elapsed)

    def apply(self, seq, gains):
        with self.lock:
            if self.fault or not self.enabled:
                raise SafetyError('Mock device not armed')
            self.applied, self.apply_t = seq, self.t
            self.kp, self.ki = gains['kp'], gains['ki']
            self.deadline = time.monotonic() + self.p['safety']['action_lease_ms'] / 1000
            return self.frame()

    def window(self, ack, duration_ms):
        frames = []
        with self.lock:
            for _ in range(round(duration_ms / 5)):
                error = self.ref - self.speed
                self.integral = max(-2.0, min(2.0, self.integral + .005 * self.ki * error))
                self.current = max(-3.0, min(3.0, self.kp * error + self.integral))
                # Reproducible, seed-dependent inertia, load and damping. No motor fidelity claim.
                inertia = 1 + .08 * (self.seed % 5)
                load = 35 + 6 * (self.seed % 7)
                acceleration = (1400 * self.current - .8 * self.speed - load) / inertia
                self.speed += .005 * acceleration
                self.previous_error = error
                self.seq += 1
                self.t += 5000
                self.elapsed += 5
                frames.append(self.frame())
            return frames

    def stop(self):
        with self.lock:
            self.enabled = False
            self.current = 0.0
            return True

    def close(self):
        self.stop()


class SerialDevice:
    """Single serial owner, continuously reading even while MATLAB is computing."""
    def __init__(self, p, output=None):
        try:
            import serial
        except ImportError as exc:
            raise SafetyError('Live mode requires pyserial (see requirements-serial.txt)') from exc
        self.p = p
        self.cv = threading.Condition()
        self.write_lock = threading.Lock()
        self.frames = collections.deque(maxlen=4096)
        self.error = None
        self.hello = None
        self.closed = False
        self.last_rx = time.monotonic()
        self.raw_log = (Path(output) / 'serial-raw.jsonl').open('w',encoding='utf-8') if output else None
        # Explicit DTR/RTS before open; target reset behavior still needs verification.
        self.port = serial.Serial(port=None, baudrate=p['device']['baudrate'], timeout=.02, write_timeout=.1)
        self.port.dtr = self.port.rts = False
        self.port.port = p['device']['port']
        self.port.open()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.send({'type': 'hello', 'profile_id': p['profile_id']})
            self.wait(lambda: self.hello is not None, 2)
            h = self.hello
            for key in ('protocol_id', 'firmware_id'):
                if h.get(key) != p['device'][key]:
                    raise SafetyError('Firmware handshake identity mismatch')
            required = {'atomic_gains', 'applied_feedback', 'lease', 'link_watchdog', 'fault_latch', 'single_owner'}
            if not required.issubset(set(h.get('capabilities', []))) or h.get('profile_id') != p['profile_id']:
                raise SafetyError('Firmware capabilities/profile mismatch')
            self.boot_id = h['boot_id']
            self.wait(lambda: bool(self.frames), 2)
        except BaseException:
            self.close()
            raise

    def send(self, obj):
        with self.write_lock:
            self.port.write(encode_frame(obj))

    def _read(self):
        buf = bytearray()
        try:
            while not self.closed:
                data = self.port.read(1024)
                for byte in data:
                    buf.append(byte)
                    if len(buf) > MAX_LINE:
                        raise SafetyError('RX frame overflow')
                    if byte == 10:
                        if self.raw_log:
                            self.raw_log.write(json.dumps({'host_monotonic':time.monotonic(), 'frame_hex':buf.hex()}) + '\n')
                            self.raw_log.flush()
                        f = decode_frame(bytes(buf))
                        buf.clear()
                        with self.cv:
                            self.last_rx = time.monotonic()
                            if f.get('type') == 'hello':
                                if self.hello is not None:
                                    raise SafetyError('Device reboot/new handshake during session')
                                self.hello = f
                            elif f.get('type') == 'telemetry':
                                telemetry_check(f, self.p)
                                if self.hello is None or f.get('boot_id') != self.hello.get('boot_id'):
                                    raise SafetyError('Unknown boot identity')
                                if self.frames:
                                    prev = self.frames[-1]
                                    if f['seq'] != prev['seq'] + 1 or f['t_us'] <= prev['t_us']:
                                        raise SafetyError('Sequence gap/reorder or clock reset')
                                    if (f['t_us'] - prev['t_us']) / 1000 > self.p['safety']['max_frame_gap_ms']:
                                        raise SafetyError('Excessive device frame gap')
                                self.frames.append(f)
                            else:
                                raise SafetyError('Unknown firmware response')
                            self.cv.notify_all()
        except BaseException as exc:
            with self.cv:
                self.error = str(exc)
                self.cv.notify_all()

    def wait(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        with self.cv:
            while not predicate():
                if self.error:
                    raise SafetyError(self.error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SafetyError('Firmware response timeout')
                self.cv.wait(min(.02, remaining))
            if self.error:
                raise SafetyError(self.error)

    def frame(self):
        with self.cv:
            if self.error:
                raise SafetyError(self.error)
            if time.monotonic() - self.last_rx > self.p['safety']['max_frame_gap_ms'] / 1000:
                raise SafetyError('Telemetry stale')
            return copy.deepcopy(self.frames[-1])

    def reset(self, seed, ref):
        if self.frame()['enabled']:
            raise SafetyError('Start requires verified disabled feedback')
        before = self.frame()['seq']
        self.send(dict(type='begin', speed_ref=ref, profile_id=self.p['profile_id'],
                       lease_ms=self.p['safety']['action_lease_ms']))
        self.wait(lambda: bool(self.frames) and self.frames[-1]['seq'] > before and self.frames[-1]['enabled'],
                  self.p['safety']['max_apply_latency_ms'] / 1000)
        f = self.frame()
        for g in ('kp', 'ki'):
            if f[g] != f32(self.p['controller'][g + '_baseline']):
                raise SafetyError('Start did not restore baseline')
        return f

    def apply(self, seq, gains):
        self.send(dict(type='gains', command_seq=seq, kp=gains['kp'], ki=gains['ki'],
                       lease_ms=self.p['safety']['action_lease_ms']))
        self.wait(lambda: bool(self.frames) and self.frames[-1]['applied_seq'] >= seq,
                  self.p['safety']['max_apply_latency_ms'] / 1000)
        with self.cv:
            matching = [f for f in self.frames if f['applied_seq'] == seq]
            if not matching:
                raise SafetyError('Applied ACK skipped')
            ack = copy.deepcopy(matching[0])
        if not ack['enabled'] or any(ack[g] != gains[g] for g in ('kp', 'ki')):
            raise SafetyError('Firmware rejected/modified command')
        return ack

    def window(self, ack, duration_ms):
        target = ack['t_apply_us'] + round(duration_ms * 1000)
        self.wait(lambda: self.frames[-1]['t_us'] >= target,
                  (duration_ms + self.p['safety']['max_frame_gap_ms']) / 1000)
        with self.cv:
            frames = [copy.deepcopy(f) for f in self.frames
                      if f['t_us'] > ack['t_apply_us']]
        end = next((i for i, f in enumerate(frames) if f['t_us'] >= target), None)
        if end is None:
            raise SafetyError('Response history incomplete')
        return frames[:end + 1]

    def stop(self):
        try:
            before = self.frames[-1]['seq'] if self.frames else -1
            self.send({'type': 'stop'})
            # Continue reader while confirming a fresh disabled frame, even if already faulted.
            deadline = time.monotonic() + .3
            with self.cv:
                while time.monotonic() < deadline:
                    if self.frames and self.frames[-1]['seq'] > before and not self.frames[-1]['enabled']:
                        return True
                    self.cv.wait(.01)
            return False
        except Exception:
            return False

    def close(self):
        self.stop()
        self.closed = True
        if hasattr(self, 'reader'):
            self.reader.join(.2)
        self.port.close()
        if self.raw_log:
            self.raw_log.close()


class Engine:
    def __init__(self, profile, output, device=None, live=False):
        validate_runtime(profile, live)
        self.p, self.live = profile, live
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.run_id = str(uuid.uuid4())
        self.log = (self.output / 'transitions.jsonl').open('w', encoding='utf-8')
        self.events = (self.output / 'events.jsonl').open('w', encoding='utf-8')
        self.device = device or (SerialDevice(profile, self.output) if live else MockDevice(profile))
        self.lock = threading.RLock()
        self.active = self.closed = False
        self.latched = None
        self.seq = self.device.frame()['applied_seq']
        self.episode = 0
        self.session_seconds = 0.0
        self.in_step = False
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()
        (self.output / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')

    def event(self, kind, **details):
        with self.lock:
            self.events.write(json.dumps(dict(event=kind, monotonic=time.monotonic(), **details), allow_nan=False) + '\n')
            self.events.flush()

    def abort(self, reason):
        with self.lock:
            if self.latched is None:
                self.latched = reason
                self.active = False
                # Monitor never needs the RPC/gradient lock. MCU lease covers a hung write/host.
                confirmed = self.device.stop()
                self.event('latched_stop', reason=reason, disabled_feedback_confirmed=confirmed)

    def _monitor(self):
        while not self.closed:
            try:
                with self.lock:
                    active = self.active
                    overdue = active and time.monotonic() >= self.lease_deadline
                    trial_overdue = active and time.monotonic() - self.episode_wall_start >= self.p['safety']['max_trial_seconds']
                if overdue:
                    self.abort('Host action lease/learner progress timeout')
                elif trial_overdue:
                    self.abort('Wall-clock trial budget exhausted')
                elif active:
                    frame = self.device.frame()
                    telemetry_check(frame, self.p)
                    if not frame['enabled']:
                        raise SafetyError('Unexpected disabled feedback during motion')
            except Exception as exc:
                self.abort(str(exc))
            time.sleep(.01)

    def reset(self, seed, ref_index, policy_version, approved_policy=None):
        if not integer(seed, 1) or not integer(ref_index) or ref_index >= len(self.p['runtime']['speed_refs_rpm']):
            raise SafetyError('Invalid fixture seed/reference index')
        if not isinstance(policy_version, str) or not policy_version or len(policy_version) > 128:
            raise SafetyError('Invalid policy identity')
        if self.live and policy_version not in {'baseline', approved_policy}:
            raise SafetyError('Live policy version has not been explicitly selected at bridge launch')
        with self.lock:
            if self.latched or self.active or self.in_step:
                raise SafetyError(self.latched or 'Stop current episode before reset')
            if self.session_seconds >= self.p['safety']['max_session_seconds']:
                raise SafetyError('Session motion budget exhausted')
            f = self.device.reset(seed, self.p['runtime']['speed_refs_rpm'][ref_index])
            telemetry_check(f, self.p)
            self.f, self.state = f, state_from(f)
            self.episode += 1
            self.step_index = 0
            self.episode_ms = 0.0
            self.episode_wall_start = time.monotonic()
            self.policy_version = policy_version
            self.active = True
            self.lease_deadline = time.monotonic() + min(self.p['safety']['action_lease_ms'],
                                                       self.p['safety']['learner_progress_timeout_ms']) / 1000
            self.event('begin', episode_id=str(self.episode), policy_version=policy_version, seed=seed)
            return dict(observation=observation(self.state, self.p), state=self.state,
                        simulation_only=not self.live)

    def step(self, action):
        with self.lock:
            if not self.active or self.latched or self.in_step:
                raise SafetyError(self.latched or 'No active episode/concurrent command')
            gains = map_action(action, self.state, self.p)
            self.in_step = True
            self.seq += 1
            seq, start, state = self.seq, self.f, copy.deepcopy(self.state)
        try:
            ack = self.device.apply(seq, gains)
            telemetry_check(ack, self.p)
            frames = self.device.window(ack, self.p['runtime']['window_ms'])
            if not frames:
                raise SafetyError('Empty response window')
            for f in frames:
                telemetry_check(f, self.p)
                if not f['enabled'] or f['applied_seq'] != seq or any(f[g] != gains[g] for g in ('kp', 'ki')):
                    raise SafetyError('Another writer or disable during response window')
            end = frames[-1]
            gaps = [(b['t_us'] - a['t_us']) / 1000 for a, b in zip([ack] + frames[:-1], frames)]
            error_mse = sum(((f['speed_ref'] - f['speed']) / self.p['runtime']['state_scale'][2]) ** 2 for f in frames) / len(frames)
            current_mse = sum((f['current'] / self.p['safety']['current_limit_a']) ** 2 for f in frames) / len(frames)
            reward = -error_mse - .05 * current_mse - .001 * sum(a * a for a in action)
            duration = (end['t_us'] - start['t_us']) / 1000
            self.episode_ms += duration
            self.session_seconds += duration / 1000
            truncated = (self.step_index + 1 >= self.p['runtime']['max_steps'] or
                         self.step_index + 1 >= self.p['safety']['max_commands_per_trial'] or
                         self.episode_ms >= self.p['safety']['max_trial_seconds'] * 1000 or
                         self.session_seconds >= self.p['safety']['max_session_seconds'])
            next_state = state_from(end)
            # End before the next action could exceed a device-time budget.
            reserve = self.p['runtime']['window_ms'] + self.p['safety']['max_apply_latency_ms']
            truncated = truncated or (self.episode_ms + reserve > self.p['safety']['max_trial_seconds'] * 1000 or
                                      self.session_seconds * 1000 + reserve > self.p['safety']['max_session_seconds'] * 1000)
            row = dict(schema_version=1, run_id=self.run_id, episode_id=str(self.episode),
                       profile_id=self.p['profile_id'], firmware_id=self.p['device']['firmware_id'],
                       protocol_id=PROTOCOL, policy_version=self.policy_version, step=self.step_index,
                       state=state, next_state=next_state, action_normalized=action,
                       action_proposed=gains, action_applied={'kp': end['kp'], 'ki': end['ki']},
                       command_seq=seq, applied_command_seq=ack['applied_seq'],
                       next_applied_command_seq=end['applied_seq'], t_state_us=start['t_us'],
                       t_apply_us=ack['t_apply_us'], t_next_us=end['t_us'],
                       telemetry_seq_start=start['seq'], telemetry_seq_end=end['seq'],
                       max_frame_gap_ms=max(gaps), reward=reward, terminated=False, truncated=truncated,
                       learner_eligible=True, safety_intervention=False,
                       stop_reason='episode_limit' if truncated else 'none',
                       metrics=dict(error_mse_normalized=error_mse, current_mse_normalized=current_mse,
                                    peak_current_a=max(abs(f['current']) for f in frames),
                                    overshoot_rpm=max(0, max((f['speed'] - f['speed_ref']) * (1 if f['speed_ref'] >= 0 else -1) for f in frames)),
                                    saturation_fraction=sum(abs(f['current']) >= 2.99 for f in frames) / len(frames)))
            errors = check_transition(row, self.p)
            if errors:
                raise SafetyError('; '.join(errors))
            with self.lock:
                if self.latched:
                    raise SafetyError(self.latched)
                self.f, self.state = end, next_state
                self.step_index += 1
                self.log.write(json.dumps(row, allow_nan=False) + '\n')
                self.log.flush()
                self.lease_deadline = time.monotonic() + min(self.p['safety']['action_lease_ms'],
                                                           self.p['safety']['learner_progress_timeout_ms']) / 1000
                if truncated:
                    self.active = False
                    confirmed = self.device.stop()
                    self.event('episode_end', disabled_feedback_confirmed=confirmed)
                    if not confirmed:
                        raise SafetyError('Trial ended without confirmed disabled feedback')
            return dict(observation=observation(next_state, self.p), reward=reward, terminated=False,
                        truncated=truncated, transition=row)
        except Exception as exc:
            self.abort(str(exc))
            self.event('excluded_interval', command_seq=seq, reason=str(exc))
            raise
        finally:
            with self.lock:
                self.in_step = False

    def stop(self):
        if self.active:
            # Unknown operator-stopped endpoint cannot be silently joined to a new learning episode.
            self.abort('Operator stop during incomplete episode')
        else:
            confirmed = self.device.stop()
            self.event('stop', disabled_feedback_confirmed=confirmed)
            if not confirmed:
                self.abort('STOP unconfirmed')
        return {'stopped': True, 'fault_latched': self.latched}

    def close(self):
        self.stop()
        self.closed = True
        self.monitor.join(.3)
        self.device.close()
        self.log.close()
        self.events.close()


def serve(engine, port, token, approved_policy=None):
    with socket.socket() as server:
        server.bind(('127.0.0.1', port))
        server.listen(1)
        print(json.dumps({'bridge_ready': True, 'port': server.getsockname()[1],
                          'simulation_only': not engine.live}), flush=True)
        shutdown = False
        while not shutdown:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(.2)
                pending = bytearray()
                authenticated = False
                try:
                    while not shutdown:
                        try:
                            data = conn.recv(4096)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        pending.extend(data)
                        if len(pending) > MAX_LINE:
                            raise SafetyError('RPC frame too large')
                        while b'\n' in pending:
                            line, _, rest = pending.partition(b'\n')
                            pending = bytearray(rest)
                            req = decode_json(line.decode('utf-8'))
                            if not isinstance(req, dict) or nonfinite_paths(req):
                                raise SafetyError('Invalid RPC object')
                            if not authenticated:
                                if req.get('op') != 'hello' or not secrets.compare_digest(str(req.get('token', '')), token):
                                    raise SafetyError('RPC authentication failed')
                                authenticated = True
                                result = dict(profile=engine.p, simulation_only=not engine.live)
                            else:
                                op = req.get('op')
                                if op == 'reset':
                                    result = engine.reset(req['seed'], req['ref_index'], req['policy_version'], approved_policy)
                                elif op == 'step':
                                    result = engine.step(req['action'])
                                elif op == 'stop':
                                    result = engine.stop()
                                elif op == 'shutdown':
                                    result = engine.stop()
                                    shutdown = True
                                else:
                                    raise SafetyError('Unknown RPC operation')
                            conn.sendall((json.dumps(dict(ok=True, result=result), allow_nan=False) + '\n').encode('utf-8'))
                except Exception as exc:
                    if authenticated and engine.active:
                        engine.abort('RPC failure: ' + str(exc))
                    try:
                        conn.sendall((json.dumps(dict(ok=False, error=str(exc))) + '\n').encode('utf-8'))
                    except OSError:
                        pass
                finally:
                    if authenticated and engine.active:
                        engine.abort('Learner disconnected during motion')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, default=47653)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--transport', choices=['mock', 'serial'], default='mock')
    parser.add_argument('--allow-live', action='store_true', help='Explicit operator live-motion selection')
    parser.add_argument('--approved-policy', help='Exact reviewed policy identity allowed for live evaluation')
    args = parser.parse_args()
    live = args.transport == 'serial'
    if live and not args.allow_live:
        parser.error('Serial motion requires explicit --allow-live and complete device validation')
    p = load_json(args.profile)
    validate_runtime(p, live)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'transitions.jsonl').exists():
        parser.error('Use a fresh output directory; logs must not be overwritten')
    token_path = Path(args.token_file)
    if token_path.exists():
        token = token_path.read_text(encoding='utf-8').strip()
        if len(token) < 32:
            parser.error('Token file must contain at least 32 characters')
    else:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(32)
        token_path.write_text(token, encoding='utf-8')
    engine = Engine(p, output, live=live)
    try:
        serve(engine, args.port, token, args.approved_policy)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
