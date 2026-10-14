"""Audit actual v26 gain ACKs and reference clocks; no performance claims."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from speedloop_motion_handshake import PHASE_MASK
from speedloop_stream_training import CausalStream
import speedloop_upper8_reference_v26 as runtime


def audit(folder, contract, index, output, *, runtime_profile=runtime):
    runtime = runtime_profile
    folder, contract, output = map(Path, (folder, contract, output))
    summary_path = folder / 'trial/summary.json'
    summary = json.loads(summary_path.read_text())
    cfg = json.loads(contract.read_text())
    if any(cfg.get(k) != v for k, v in runtime.expected_schedule(index).items()):
        raise ValueError('Unknown predeclared v26 schedule')
    if runtime.sha(contract) != summary.get('schedule_contract_sha256'):
        raise ValueError('Contract changed after capture')
    if (summary.get('firmware_id') != runtime.IDENTITY
            or summary.get('bin_sha256') != runtime.IMAGE_SHA
            or summary.get('actor_applied') is not False
            or not all(summary.get(k) for k in ('passed', 'protocol_stop_acknowledged',
                'core_halted_after_physical_shutdown', 'can_released_after_shutdown'))
            or summary.get('final_irq_fault') != 0 or summary.get('final_tx_fault') != 0):
        raise ValueError('Incomplete exact-image stopped trial')
    board = summary['final_board_state']
    if (board['tim1_bdtr'] & 0x8000 or board['tim1_ccer'] & PHASE_MASK
            or board['gpioa_moder'] & 0x3f0000 != 0x150000
            or board['gpiob_moder'] & 0xfc000000 != 0x54000000
            or board['gpioa_odr'] & 0x700 or board['gpiob_odr'] & 0xe000):
        raise ValueError('Six physical outputs not inhibited')
    timing = summary['trial_timing']
    motion_seconds = (timing['last_us'] - timing['started_us']) / 1e6
    if not 0 < motion_seconds <= cfg['reserved_motion_seconds'] or timing['fault']:
        raise ValueError('Motion budget or timing fault')
    commands, packets = {}, []
    previous = boot = started = None
    event_path = folder / 'stream/events.jsonl'
    for line in event_path.read_text().splitlines():
        event = json.loads(line)
        if event['kind'] == 'command':
            c = event['command']
            if c['type'] != 'gains':
                continue
            source = event['source']
            if (c['command_seq'] != len(commands) + 1 or source is None
                    or source != previous or c['source_t_us'] != source['t_us']):
                raise ValueError('Missing command source, duplicate or sequence gap')
            if (c['kp'] not in runtime.LEVELS or c['ki'] != runtime.KI
                    or abs(c['kp'] - source['kp']) > cfg['host_single_kp_step_limit'] + 1e-9):
                raise ValueError('Unmeasured gain or command step outside host scope')
            commands[c['command_seq']] = c
            continue
        if event['kind'] != 'telemetry':
            raise ValueError('Unknown journal event')
        p, proof = event['packet'], event['stage_proof']
        boot = p['boot_id'] if boot is None else boot
        if (boot != p['boot_id'] or p['fault'] or previous and
                (p['seq'] != previous['seq'] + 1 or not 15000 <= p['t_us'] - previous['t_us'] <= 25000)):
            raise ValueError('Boot, fault or telemetry sequence/time mismatch')
        if not all(math.isfinite(p[k]) for k in ('speed_ref', 'speed', 'current', 'vbus', 'kp', 'ki')):
            raise ValueError('Nonfinite telemetry')
        if p['enabled'] and (abs(p['speed']) >= 1800 or not 0 <= p['current'] < 2
                or not 18 <= p['vbus'] <= 30 or not runtime.reference_matches(p['elapsed_ms'], p['speed_ref'])):
            raise ValueError('Physical boundary or actual reference clock violation')
        if p['applied_seq']:
            c = commands.get(p['applied_seq'])
            if (c is None or [c['kp'], c['ki']] != [p['kp'], p['ki']]
                    or not c['source_t_us'] <= p['t_apply_us'] <= c['expires_us']):
                raise ValueError('Actual gain acknowledgement missing or invalid')
        if p['enabled'] and p['elapsed_ms'] >= 3900:
            if not CausalStream.valid_stage(proof, p):
                raise ValueError('Missing actual RunStage proof')
            started = proof['started_us'] if started is None else started
            if started != proof['started_us']:
                raise ValueError('Stage clock origin changed')
        packets.append(p)
        previous = p
    raw = [json.loads(s) for s in (folder / 'trial/telemetry.jsonl').read_text().splitlines()]
    if raw != packets or len(commands) != summary['actual_gain_commands']:
        raise ValueError('Raw packets or command total differs from journal')
    if started != timing['started_us']:
        raise ValueError('Trial and stage timing disagree')
    slots, coverage = [], Counter()
    for slot, level in enumerate(cfg['pattern']):
        begin = cfg['plateau_start_ms'] + slot * cfg['plateau_ms']
        end = begin + cfg['plateau_ms']
        target = cfg['exact_kp_levels'][level]
        within = [p for p in packets if p['enabled'] and begin <= p['elapsed_ms'] < end]
        matched = [p for p in within if p['applied_seq'] and p['kp'] == target and p['ki'] == runtime.KI]
        if not matched:
            raise ValueError('Declared target never actually acknowledged')
        effective = max(begin, (matched[0]['t_apply_us'] - started) / 1000)
        if effective > begin + 100:
            raise ValueError('Declared target not actually applied within 100 ms')
        selected = [p for p in within if effective + cfg['analysis_settle_ms'] <= p['elapsed_ms']
            < end - cfg['analysis_end_margin_ms']]
        if (len(selected) < 8 or selected[-1]['t_us'] - selected[0]['t_us'] < 140000
                or any(p['kp'] != target or p['ki'] != runtime.KI for p in selected)):
            raise ValueError('Incomplete or mixed-action target response')
        for p in selected:
            coverage[(p['speed_ref'], level)] += 1
        slots.append(dict(slot=slot, level=level, target_kp=target, fixed_ki=runtime.KI,
            planned_begin_ms=begin, planned_end_ms=end, first_actual_ack_ms=matched[0]['elapsed_ms'],
            actual_apply_delay_ms=effective-begin,
            telemetry_ACK_delay_ms=matched[0]['elapsed_ms']-begin,
            target_effective_ms=effective, response_packets=len(selected),
            actual_references_rpm=sorted({p['speed_ref'] for p in selected}),
            first_seq=selected[0]['seq'], last_seq=selected[-1]['seq']))
    required={(r,l) for r in (950,1000,1050) for l in (0,2,4,6,8)}
    if 'planned_reference_target_categories' in cfg:
        required={tuple(x) for x in cfg['planned_reference_target_categories']}
    if not required <= set(coverage):
        raise ValueError('Actual reference/target coverage incomplete')
    report = dict(passed=True, boot_id=boot, whole_boot_role=cfg['whole_boot_role'],
        actual_motion_seconds=motion_seconds, complete_packets=len(packets), actual_gain_commands=len(commands),
        actual_slots=slots, reference_target_packet_counts=[dict(reference_rpm=r, target_level=l, packets=n)
            for (r, l), n in sorted(coverage.items())],
        reference_changes_inside_gain_slots_allowed=True,
        required_reference_target_categories=[list(x) for x in sorted(required)],
        reference_crossing_training_windows_must_be_rejected=True,
        training_data_capture_only=True, independent_performance_evaluation=False,
        actor_applied=False, training_performed=False, candidate_admission=False,
        deployment_allowed=False, performance_claim_allowed=False,
        hashes={str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (contract, summary_path, event_path, folder / 'trial/telemetry.jsonl')})
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('Audit output already exists')
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('actual_slots', 'hashes')}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('folder', 'contract', 'output'):
        p.add_argument('--' + key, required=True)
    p.add_argument('--index', type=int, choices=(0, 1), required=True)
    p.add_argument('--profile', choices=('v26-initial','v26-joint-support','v26-plus4-hold'), default='v26-initial')
    a = p.parse_args()
    profile=runtime
    if a.profile=='v26-joint-support':
        import speedloop_reference_support_probe as profile
    elif a.profile=='v26-plus4-hold':
        import speedloop_reference_plus4_hold as profile
    audit(a.folder, a.contract, a.index, a.output,runtime_profile=profile)
