"""One 3 s, 1000 rpm physical PI trial on the exact reviewed motion-v5 image.

Explicit experiment exception: no measured temperature channel. Does not change
the normal training gates. Optional MATLAB shadow Actor cannot write gains.
No gradient updates, random exploration or flash.
Retains actual command/apply timestamps and verifies physical output shutdown.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import struct
import subprocess
import time

import can_transport as wire
from speedloop_motion_handshake import IDENTITY, PHASE_MASK, REGS, RAM
from speedloop_motion_prepare import ENERGIZED_IMAGE_SHA
from speedloop_board_stop import inhibit

BASE_KP, BASE_KI = .003389, .00144
STOP_SECONDS = 2.80
GAIN_CUTOFF_SECONDS = 2.70
FINAL_GAIN_SECONDS = 2.72
FINAL_GAIN_DEADLINE_SECONDS = 2.75
GAIN_INTERVAL_SECONDS = .050


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def planned_gains(elapsed_ms, ki_probe_sign=0, mode=None):
    # A small deterministic local probe, well inside the existing step limit.
    mode = mode or ('ki_probe' if ki_probe_sign else 'kp_probe')
    if mode == 'baseline':
        if ki_probe_sign: raise ValueError('Baseline cannot request a Ki probe')
        return f32(BASE_KP), f32(BASE_KI)
    if mode == 'ki_probe':
        if ki_probe_sign not in (-1, 1): raise ValueError('Ki probe needs a signed direction')
        ki = BASE_KI + ki_probe_sign * .25 * .000144 if 2200 <= elapsed_ms < 2700 else BASE_KI
        return f32(BASE_KP), f32(ki)
    if mode != 'kp_probe' or ki_probe_sign: raise ValueError('Conflicting gain mode')
    return f32(BASE_KP * (1.04 if 2400 <= elapsed_ms < 2600 else 1)), f32(BASE_KI)


def gain_due(now, begin_at, next_gain, stop_at):
    return (begin_at is not None and stop_at is None and next_gain is not None and
            now >= next_gain and now-begin_at < GAIN_CUTOFF_SECONDS)


def final_gain_due(now, begin_at, stop_at, already_sent):
    return (begin_at is not None and stop_at is None and not already_sent and
            now-begin_at >= FINAL_GAIN_SECONDS)


def acknowledgement_ready(actual, expected, now, due):
    if actual==expected: return True
    if now-due>=.025:
        raise RuntimeError('Actual action acknowledgement exceeded its decision deadline')
    return False


def check_telemetry(obj, last, sent):
    if last and (obj['seq'] != last['seq'] + 1 or obj['t_us'] <= last['t_us']):
        raise RuntimeError('Telemetry order failure')
    if obj['fault'] or obj['temperature_c'] is not None:
        raise RuntimeError('Board fault or unexpected temperature channel')
    if not all(math.isfinite(obj[k]) for k in wire.FLOATS if k != 'temperature_c'):
        raise RuntimeError('Invalid physical observation')
    if abs(obj['speed']) >= 1800 or obj['current'] >= 2 or not 18 <= obj['vbus'] <= 30:
        raise RuntimeError('Existing speed/current/bus boundary exceeded')
    seq = obj['applied_seq']
    if seq:
        cmd = sent.get(seq)
        if (not cmd or obj['kp'] != cmd['kp'] or obj['ki'] != cmd['ki'] or
                not cmd['source_t_us'] <= obj['t_apply_us'] <= cmd['expires_us'] or
                (last and seq < last['applied_seq'])):
            raise RuntimeError('Actual gain/sequence/apply-time mismatch')


def shutdown(target, symbols):
    # Debug halt alone is not a stop. Drop MOE and all six phase gates first.
    inhibit(target)
    target.write8(symbols['Motor_state'], 0)
    target.halt()
    values = {name: target.read32(addr) for name, addr in REGS.items()}
    if (values['tim1_bdtr'] & 0x8000 or values['tim1_ccer'] & PHASE_MASK or
            values['gpioa_moder'] & 0x3f0000 != 0x150000 or
            values['gpiob_moder'] & 0xfc000000 != 0x54000000 or
            values['gpioa_odr'] & 0x700 or values['gpiob_odr'] & 0xe000):
        raise RuntimeError('Physical shutdown readback failed')
    return values


def trial(a):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    build, output = Path(a.build).resolve(), Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents:
        raise ValueError('Use the approved temporary root')
    if not a.power_confirmed or not a.authorized_no_thermal_trial:
        raise ValueError('Power state and explicit no-thermal experiment scope required')
    output.mkdir(parents=True, exist_ok=True)
    summary = json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if (summary['build_id'] != IDENTITY or not summary['passed'] or
            summary['bin_sha256'] != ENERGIZED_IMAGE_SHA):
        raise ValueError('Only the exact reviewed motion-v5 image is accepted')
    nm = subprocess.run([a.nm, '--defined-only', str(build/'speedloop-pi-review.elf')],
                        capture_output=True, text=True, check=True)
    symbols = {s[2]: int(s[0], 16) for line in nm.stdout.splitlines()
               if len(s := line.split()) == 3}
    boot = int(Path(a.boot_token_file).read_text(encoding='ascii').strip(), 16)
    nonce = secrets.randbits(64) or 1
    result = dict(schema_version=1, utc=datetime.now(timezone.utc).isoformat(), passed=False,
                  firmware_id=IDENTITY, bin_sha256=ENERGIZED_IMAGE_SHA,
                  hardware_accessed=True, motion_command_sent=False, td3_training_performed=False,
                  temperature_c=None, thermal_exception='user authorized this bounded trial only',
                  current_conversion_independently_calibrated=False,
                  independent_cpu_stall_watchdog_integrated=False,
                  speed_ref_rpm=1000, maximum_motion_seconds=3, host_stop_seconds=STOP_SECONDS)
    result['gain_interval_ms'] = GAIN_INTERVAL_SECONDS*1000
    result['ki_probe_sign'] = int(getattr(a, 'ki_probe_sign', 0))
    result['ki_probe_fraction_of_local_step'] = .25 if result['ki_probe_sign'] else 0
    result['ki_probe_window_ms'] = [2200, 2700] if result['ki_probe_sign'] else []
    result['host_clock'] = 'QueryPerformanceCounter via perf_counter'
    result['host_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    telemetry, commands, sent = [], [], {}
    link = None
    verified = False
    wire_seq, transfer, action_seq = 0, 0, 0
    hello = None
    begin_at = stop_at = next_gain = None
    final_gain_sent = False
    shadow = None
    shadow_records = []
    shadow_by_seq = {}
    apply_actor_kp = bool(getattr(a, 'apply_shadow_kp', False))
    ki_probe_sign = int(getattr(a, 'ki_probe_sign', 0))
    if ki_probe_sign not in (-1, 0, 1):
        raise ValueError('Ki probe sign must be -1, 0 or +1')
    gain_mode = getattr(a, 'gain_mode', None) or ('ki_probe' if ki_probe_sign else 'kp_probe')
    planned_gains(0, ki_probe_sign, gain_mode) # Validate before attaching to hardware.
    if ki_probe_sign and (apply_actor_kp or getattr(a, 'shadow_port', None)):
        raise ValueError('Ki collection cannot be combined with an Actor/shadow trial')
    result['gain_mode'] = 'actor_kp' if apply_actor_kp else 'baseline' if getattr(a, 'shadow_port', None) else gain_mode
    session = ConnectHelper.session_with_chosen_probe(unique_id=a.uid, target_override='cortex_m',
        connect_mode='attach', frequency=1000000, no_config=True,
        options={'resume_on_disconnect': False,'cache.enable_memory':False,'cache.enable_register':False}, blocking=False)
    if session is None:
        raise RuntimeError('No selected probe')
    with session:
        target = session.target
        def send(obj, source=None):
            nonlocal wire_seq, transfer
            if obj['type'] != 'hello': wire_seq += 1
            transfer = (transfer + 1) % 256
            expires = source['t_us'] + 100000 if obj['type'] in ('begin', 'gains') else 0
            record = dict(obj, wire_seq=wire_seq, source_t_us=source['t_us'] if source else None,
                          expires_us=expires, host_monotonic=time.perf_counter())
            if obj['type'] == 'gains': sent[obj['command_seq']] = record
            commands.append(record)
            packet = wire.pack(obj, nonce, 0 if obj['type'] == 'hello' else boot, wire_seq, expires)
            for frame in wire.fragment(packet, transfer):
                link.send(frame)
                time.sleep(.001)
        try:
            shadow_port = getattr(a, 'shadow_port', None)
            shadow_token = getattr(a, 'shadow_token_file', None)
            if bool(shadow_port) != bool(shadow_token):
                raise ValueError('Both MATLAB shadow port and private token are required')
            if apply_actor_kp and not shadow_port:
                raise ValueError('Actor application requires the MATLAB shadow server')
            if shadow_port:
                from speedloop_shadow import ShadowClient
                shadow = ShadowClient(shadow_port, shadow_token)
                if not shadow.ready.wait(2):
                    raise RuntimeError('MATLAB shadow handshake failed before any board command: '+str(shadow.error))
                result['shadow_mode'] = ('MATLAB Actor Kp applied; Ki fixed at baseline'
                                         if apply_actor_kp else
                                         'fixed-baseline-PI; MATLAB suggestions recorded only')
                result['actor_gain_commands_sent'] = 0
                result['actor_applied'] = apply_actor_kp
            image = bytes(target.read_memory_block8(0x08000000, summary['binary_bytes']))
            if hashlib.sha256(image).hexdigest() != ENERGIZED_IMAGE_SHA:
                raise RuntimeError('Flash mismatch; no commands sent')
            values = {name: target.read32(addr) for name, addr in REGS.items()}
            if (target.get_state() != Target.State.HALTED or values['device_id'] & 0xfff != 0x468 or
                    values['tim1_ccer'] & PHASE_MASK or not values['tim1_bdtr'] & 0x8000 or
                    values['gpioa_moder'] & 0x3f0000 != 0x150000 or
                    values['gpiob_moder'] & 0xfc000000 != 0x54000000 or
                    values['gpioa_odr'] & 0x700 or values['gpiob_odr'] & 0xe000 or
                    target.read8(symbols['Motor_state']) or not target.read8(symbols['ADC_offset']) or
                    target.read32(symbols['irq_fault']) or not target.read32(symbols['endpoint_ready']) or
                    any(target.read_memory_block8(symbols['motor_td3_g431_debugger_boot_token'], 8))):
                raise RuntimeError('Prepared phase-inhibited state invalid')
            bus = struct.unpack('<f', bytes(target.read_memory_block8(symbols['Vbus'], 4)))[0]
            result['preflight_nominal_bus_v'] = bus
            if not math.isfinite(bus) or not 18 <= bus <= 30:
                raise RuntimeError('Board bus is not 18..30 V; no CAN or motion request sent')
            result['preflight_state'] = values
            verified = True
            link = wire.PcanLink('PCAN_USBBUS1')
            rx = wire.Reassembler(allow_missing_temperature=True)
            target.resume()
            send(dict(type='hello', profile_id=IDENTITY))
            due = time.perf_counter() + 5
            while time.perf_counter() < due:
                if shadow:
                    fresh_shadow = shadow.drain()
                    shadow_records.extend(fresh_shadow)
                    for record in fresh_shadow:
                        if record.get('accepted') and record.get('telemetry_seq') is not None:
                            shadow_by_seq[int(record['telemetry_seq'])] = record
                now = time.perf_counter()
                if begin_at and not stop_at and now-begin_at >= STOP_SECONDS:
                    send(dict(type='stop')); stop_at = time.perf_counter()
                final_due = final_gain_due(now, begin_at, stop_at, final_gain_sent)
                if final_due and telemetry and telemetry[-1]['applied_seq'] != action_seq:
                    if now-begin_at >= FINAL_GAIN_DEADLINE_SECONDS:
                        raise RuntimeError('Last action acknowledgement missed final heartbeat deadline')
                    final_due = False
                regular_due = gain_due(now, begin_at, next_gain, stop_at)
                if regular_due:
                    regular_due = acknowledgement_ready(telemetry[-1]['applied_seq'],action_seq,now,next_gain)
                    if regular_due and apply_actor_kp and not shadow_by_seq.get(int(telemetry[-1]['seq'])):
                        if now - next_gain < .025:
                            regular_due = False
                        else:
                            raise RuntimeError('MATLAB Actor result missed the 25 ms action deadline')
                if regular_due or final_due:
                    last = telemetry[-1]
                    if not last['enabled'] or now-begin_at > .15 and last['applied_seq'] != action_seq:
                        raise RuntimeError('No fresh actual action acknowledgement')
                    if time.perf_counter()-last['host_received_monotonic'] >= .045:
                        raise RuntimeError('Telemetry stale; no gain refresh')
                    if apply_actor_kp and not final_due:
                        prediction = shadow_by_seq.get(int(last['seq']))
                        if not prediction or 'result' not in prediction:
                            raise RuntimeError('No accepted MATLAB Actor result for current telemetry')
                        kp = f32(prediction['result']['kp'])
                        ki = f32(BASE_KI)
                        result['actor_gain_commands_sent'] += 1
                    else:
                        kp, ki = ((f32(BASE_KP),f32(BASE_KI)) if final_due or shadow
                                  else planned_gains(last['elapsed_ms'], ki_probe_sign, gain_mode))
                    action_seq += 1
                    send(dict(type='gains', command_seq=action_seq, kp=kp, ki=ki, lease_ms=200), last)
                    next_gain = now + GAIN_INTERVAL_SECONDS
                    if final_due: final_gain_sent = True
                frame = link.receive()
                if frame is None: continue
                packet = rx.feed(frame, time.perf_counter())
                if packet is None: continue
                obj, meta = wire.unpack(packet, allow_missing_temperature=True)
                if meta['nonce'] != nonce or meta['boot'] != boot:
                    raise RuntimeError('Session identity mismatch')
                if obj['type'] == 'hello':
                    if (hello or obj['firmware_id'] != IDENTITY or obj['profile_id'] != IDENTITY or
                            set(obj['capabilities']) != set(wire.CAPABILITIES)):
                        raise RuntimeError('HELLO identity/capability mismatch')
                    hello = obj
                elif obj['type'] == 'telemetry':
                    if not hello: raise RuntimeError('Telemetry before HELLO')
                    try:
                        check_telemetry(obj, telemetry[-1] if telemetry else None, sent)
                    except Exception:
                        result['rejected_telemetry'] = obj
                        raise
                    obj['host_received_monotonic'] = time.perf_counter()
                    telemetry.append(obj)
                    if shadow:
                        shadow.submit(obj, obj['host_received_monotonic'])
                    if begin_at is None:
                        if obj['enabled']: raise RuntimeError('Unexpected pre-BEGIN motion')
                        send(dict(type='begin', profile_id=IDENTITY, speed_ref=1000, lease_ms=200), obj)
                        begin_at = time.perf_counter(); result['motion_command_sent'] = True
                    elif obj['enabled'] and next_gain is None:
                        next_gain = time.perf_counter()
                    elif stop_at and not obj['enabled'] and time.perf_counter()-stop_at >= .1:
                        result['protocol_stop_acknowledged'] = True
                        break
                    elif not obj['enabled'] and not stop_at and time.perf_counter()-begin_at > .1:
                        raise RuntimeError('Motion stopped before planned STOP')
                else: raise RuntimeError('Unexpected response')
            active = [t for t in telemetry if t['enabled']]
            acked = {t['applied_seq'] for t in active if t['applied_seq']}
            if (not result.get('protocol_stop_acknowledged') or len(active) < 20 or
                    not sent or acked != set(sent)):
                raise RuntimeError('Incomplete actual gain trial')
            post_start = [t for t in active if t['elapsed_ms'] >= 2200]
            result.update(passed=True, complete_telemetry_packets=len(telemetry), active_snapshots=len(active),
                          actual_gain_commands=len(acked), gain_pairs=sorted({(t['kp'], t['ki']) for t in active}),
                          nominal_peak_current_a=max(t['current'] for t in active),
                          peak_speed_rpm=max(abs(t['speed']) for t in active),
                          expected_post_start_snapshots=len(post_start),
                          expected_post_start_window_rmse_rpm=(sum((t['speed']-1000)**2 for t in post_start)/len(post_start))**.5 if post_start else None,
                          post_start_is_steady_state_score=False)
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            if verified:
                if link and hello and stop_at is None:
                    try: send(dict(type='stop')); time.sleep(.04)
                    except Exception as exc: result['stop_send_error'] = str(exc)
                try:
                    result['final_board_state'] = shutdown(target, symbols)
                    result['core_halted_after_physical_shutdown'] = True
                    result['final_irq_fault'] = target.read32(symbols['irq_fault'])
                    result['final_tx_fault'] = target.read32(symbols['motor_td3_g431_tx_fault'])
                    count = target.read32(symbols['motor_td3_g431_hall_edge_count'])
                    records = []
                    capacity = summary['hall_trace_capacity']
                    if capacity != 512: raise RuntimeError('Unexpected Hall trace capacity')
                    for index in range(max(0, count-capacity), count):
                        raw = bytes(target.read_memory_block8(symbols['motor_td3_g431_hall_edges']+(index%capacity)*24,24))
                        timestamp, ticks, period, rpm, code, previous, stage, valid = struct.unpack('<QIIf4B',raw)
                        records.append(dict(edge=index+1,t_us=timestamp,raw_timer_ticks=ticks,period_us=period,
                                            rpm=rpm,hall_code=code,previous_code=previous,model_stage=stage,valid=bool(valid)))
                    (output/'hall-edges.json').write_text(json.dumps(dict(total_edges=count,capacity=capacity,records=records),indent=2)+'\n',encoding='utf-8')
                except Exception as exc:
                    result['passed'] = False; result['shutdown_error'] = str(exc)
            if link:
                try: link.close(); result['can_released_after_shutdown'] = True
                except Exception as exc:
                    result['passed'] = False; result['can_release_error'] = str(exc)
            if shadow:
                result['shadow_worker_closed'] = shadow.close()
                shadow_records.extend(shadow.drain())
                result['shadow'] = shadow.summary(shadow_records)
                result['shadow_pipeline_verified'] = bool(
                    result.get('passed') and result['shadow_worker_closed'] and
                    result['shadow']['accepted'] >= 20 and not result['shadow']['worker_error'] and
                    not result['shadow']['records_dropped'])
                with (output/'shadow-predictions.jsonl').open('w',encoding='utf-8') as f:
                    for record in shadow_records: f.write(json.dumps(record,allow_nan=False)+'\n')
    for name, rows in (('telemetry', telemetry), ('commands', commands)):
        with (output/(name+'.jsonl')).open('w', encoding='utf-8') as f:
            for row in rows: f.write(json.dumps(row, allow_nan=False)+'\n')
    (output/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(result, allow_nan=False))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'output', 'nm', 'boot-token-file'): p.add_argument('--'+name, required=True)
    p.add_argument('--uid', default='0674FF554850715087183841')
    p.add_argument('--power-confirmed', action='store_true')
    p.add_argument('--authorized-no-thermal-trial', action='store_true')
    p.add_argument('--shadow-port', type=int)
    p.add_argument('--shadow-token-file')
    p.add_argument('--apply-shadow-kp', action='store_true',
                   help='Experimental single-trial mode: apply MATLAB Kp only; Ki remains baseline')
    p.add_argument('--ki-probe-sign', type=int, choices=(-1, 0, 1), default=0,
                   help='Experimental fixed-PI data collection: local Ki probe sign')
    p.add_argument('--gain-mode', choices=('baseline','kp_probe','ki_probe'),
                   help='Explicit behavior; omission preserves the historical probe entry')
    args = p.parse_args()
    raise SystemExit(0 if trial(args)['passed'] else 1)
