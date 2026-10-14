"""Audit approved baseline/-4% actual responses; no hardware access."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from speedloop_lower_commission import PATTERN, SEED, IDENTITY, IMAGE_SHA
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import lines, temporal_mean
from speedloop_context_metrics import matched_metrics


def expected_gain(elapsed):
    lower = 4000 <= elapsed < 22000 and PATTERN[int((elapsed - 4000) // 400)]
    return f32(.00325344 if lower else .003389)


def run(trial, contract, output):
    trial, contract, out = (Path(p).resolve() for p in (trial, contract, output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Use task temporary root')
    summary = json.loads((trial / 'summary.json').read_text(encoding='utf-8'))
    declared = json.loads(contract.read_text(encoding='utf-8'))
    if (not summary['passed'] or summary['actor_applied'] or summary['firmware_id'] != IDENTITY
            or summary['bin_sha256'] != IMAGE_SHA or summary['probe_pattern'] != list(PATTERN)
            or declared['pattern'] != list(PATTERN) or declared['seed'] != SEED
            or declared['operator_approved_lower_probe'] is not True
            or hashlib.sha256(contract.read_bytes()).hexdigest() != summary['schedule_contract_sha256']):
        raise ValueError('Failed physical trial or altered declared contract')
    telemetry = lines(trial / 'telemetry.jsonl')
    commands = lines(trial / 'commands.jsonl')
    if len({r['boot_id'] for r in telemetry}) != 1 or any(r['fault'] for r in telemetry):
        raise ValueError('Faulted or mixed-boot data')
    bytime = {r['t_us']: r for r in telemetry}
    applied = {r['applied_seq'] for r in telemetry}
    for command in commands:
        if command['type'] != 'gains':
            continue
        source = bytime[command['source_t_us']]
        if (command['kp'] != expected_gain(source['elapsed_ms']) or command['ki'] != f32(.00144)
                or command['command_seq'] not in applied):
            raise ValueError('Changed action or missing actual application readback')
    rows = []
    for slot, level in enumerate(PATTERN):
        start = 4000 + slot * 400
        kp = f32(.00325344 if level else .003389)
        reference = [1100, 900, 1000][slot % 9 // 3]
        response = [r for r in telemetry if r['enabled'] and start + 120 <= r['elapsed_ms'] < start + 380]
        if (len(response) < 8 or any(r['kp'] != kp or r['ki'] != f32(.00144)
                                   or r['speed_ref'] != reference for r in response)):
            raise ValueError('Missing late response or wrong actual gain/reference')
        if any(b['seq'] != a['seq'] + 1 or not 15000 <= b['t_us'] - a['t_us'] <= 25000
               for a, b in zip(response, response[1:])):
            raise ValueError('Sequence or timestamp gap')
        source_command = next(c for c in commands if c['type'] == 'gains'
            and start <= bytime[c['source_t_us']]['elapsed_ms'] < start + 400)
        source = bytime[source_command['source_t_us']]
        mse = temporal_mean([(r['speed_ref'] - r['speed']) ** 2 for r in response],
                            [r['t_us'] for r in response])
        rows.append(dict(slot=slot, level=level, cycle=slot // 9, reference_phase=slot % 9 // 3,
            speed_ref_rpm=reference, actual_kp=kp, actual_ki=f32(.00144),
            source_error_rpm=source['speed_ref'] - source['speed'], source_seq=source['seq'],
            response_sequences=[r['seq'] for r in response], response_mse_rpm2=mse,
            response_rmse_rpm=math.sqrt(mse), peak_nominal_current_a=max(r['current'] for r in response),
            peak_speed_rpm=max(abs(r['speed']) for r in response)))
    matched = matched_metrics(rows, (0, 1))
    per_reference = []
    for phase in range(3):
        arms = [[r for r in rows if r['reference_phase'] == phase and r['level'] == level] for level in (0, 1)]
        per_reference.append(dict(speed_ref_rpm=[1100, 900, 1000][phase], counts=[len(v) for v in arms],
            rmse_rpm=[math.sqrt(mean(r['response_mse_rpm2'] for r in v)) for v in arms]))
    result = dict(source='approved-real-motor-baseline-minus4-kp', boot_id=telemetry[0]['boot_id'],
        actual_slots=len(rows), independent_boots=1, actor_applied=False, fixed_ki=.00144,
        context_standardized_metrics=matched, reference_only_metrics=per_reference,
        evaluation_window_ms_relative_to_slot=[120, 380], primary_metric_changed=False,
        randomization_significance_test_performed=False,
        statistical_note='Nine randomized context offsets with five alternating cycles; slots are not independent random assignments',
        telemetry_sha256=hashlib.sha256((trial / 'telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((trial / 'commands.jsonl').read_bytes()).hexdigest(),
        contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
        hardware_accessed=False, actor_admission=False, deployment_allowed=False, performance_claim_allowed=False)
    out.mkdir(parents=True, exist_ok=False)
    for name, value in [('gain-effect-summary', result), ('slot-responses', rows)]:
        (out / (name + '.json')).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('trial', 'contract', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    run(args.trial, args.contract, args.output)
