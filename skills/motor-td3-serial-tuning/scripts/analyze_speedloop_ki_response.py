"""Actual Ki application and subsequent matched responses, no hardware."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from speedloop_ki_response import PATTERN, SEED, KI_LEVELS, IDENTITY, IMAGE_SHA, KiProbe
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import lines, temporal_mean
from speedloop_context_metrics import matched_metrics


def run(trial, contract, output):
    trial, contract, out = (Path(p).resolve() for p in (trial, contract, output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Use task temporary root')
    s = json.loads((trial / 'summary.json').read_text(encoding='utf-8'))
    c = json.loads(contract.read_text(encoding='utf-8'))
    if (not s['passed'] or s['actor_applied'] or s['firmware_id'] != IDENTITY or s['bin_sha256'] != IMAGE_SHA
            or s['probe_pattern'] != list(PATTERN) or c['pattern'] != list(PATTERN) or c['seed'] != SEED
            or c['reference_position_evaluation_ms'] != [[100,260],[500,660],[900,1000]]
            or hashlib.sha256(contract.read_bytes()).hexdigest() != s['schedule_contract_sha256']):
        raise ValueError('Changed schedule/image or failed physical trial')
    raw = lines(trial / 'telemetry.jsonl')
    commands = lines(trial / 'commands.jsonl')
    journal_present=False
    if 'stage_journal' in s:
        journal=trial.parent/'stage-journal'
        proof=json.loads((journal/'stage-journal-summary.json').read_text(encoding='utf-8'))
        if (not proof['closed'] or proof['error'] is not None or proof['actual_stage_proofs']<900
                or hashlib.sha256((journal/'events.jsonl').read_bytes()).hexdigest()!=proof['event_sha256']):
            raise ValueError('Incomplete stage journal')
        events=lines(journal/'events.jsonl')
        if [e['packet'] for e in events if e['kind']=='telemetry']!=raw:
            raise ValueError('Stage journal differs from raw telemetry')
        journal_present=True
    if len({r['boot_id'] for r in raw}) != 1 or any(r['fault'] for r in raw):
        raise ValueError('Fault or mixed boot')
    bytime = {r['t_us']: r for r in raw}
    grouped = {i: [] for i in range(15)}
    policy = KiProbe()
    for command in commands:
        if command['type'] != 'gains':
            continue
        source = bytime[command['source_t_us']]
        expected = policy.planned(source['elapsed_ms'])
        if (command['kp'], command['ki']) != expected:
            raise ValueError('Actual command differs from declared Ki schedule')
        acknowledgements = [r for r in raw if r['applied_seq'] == command['command_seq']]
        if not acknowledgements or any((r['kp'],r['ki']) != expected for r in acknowledgements):
            raise ValueError('Missing or incorrect actual gain readback')
        if 3850 <= source['elapsed_ms'] < 22000:
            segment = min(14, int((source['elapsed_ms'] + 150 - 4000) // 1200))
            grouped[segment].append(command)
    proofs = []
    rows = []
    for segment, level in enumerate(PATTERN):
        start = 4000 + segment * 1200
        phase = segment % 3
        reference = [1100,900,1000][phase]
        first = grouped[segment][0]
        ack = next(r for r in raw if r['applied_seq'] == first['command_seq'])
        planned_us = s['trial_timing']['started_us'] + start * 1000
        if ack['t_apply_us'] >= planned_us:
            raise ValueError('Ki was not applied before the planned reference transition')
        proofs.append(dict(segment=segment, actual_command_seq=first['command_seq'],
            actual_ki=ack['ki'], actual_t_apply_us=ack['t_apply_us'],
            planned_reference_t_us=planned_us, actual_lead_ms=(planned_us-ack['t_apply_us'])/1000))
        for position, (lo,hi) in enumerate(c['reference_position_evaluation_ms']):
            response = [r for r in raw if r['enabled'] and start+lo <= r['elapsed_ms'] < start+hi]
            if len(response)<4 or any(r['kp']!=f32(.003389) or r['ki']!=KI_LEVELS[level]
                                      or r['speed_ref']!=reference for r in response):
                raise ValueError('Missing or mismatched actual Ki response')
            if any(b['seq']!=a['seq']+1 or not 15000<=b['t_us']-a['t_us']<=25000
                   for a,b in zip(response,response[1:])):
                raise ValueError('Response sequence/time gap')
            mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],[r['t_us'] for r in response])
            rows.append(dict(slot=segment*3+position, segment=segment, cycle=segment//3,
                reference_phase=phase, level=level, speed_ref_rpm=reference,
                actual_kp=f32(.003389), actual_ki=KI_LEVELS[level], response_mse_rpm2=mse,
                response_rmse_rpm=math.sqrt(mse), response_sequences=[r['seq'] for r in response],
                peak_nominal_current_a=max(r['current'] for r in response),
                peak_speed_rpm=max(abs(r['speed']) for r in response)))
    result=dict(source='actual-warm-loop-ki-three-point-response', boot_id=raw[0]['boot_id'],
        independent_boots=1, reference_segments=15, matched_position_cells=45,
        level_definitions={'0':'baseline','1':'Ki -2.5%','2':'Ki +2.5%'}, actual_ki_levels=list(KI_LEVELS),
        context_standardized_metrics=matched_metrics(rows,(0,1,2)),
        actual_gain_acknowledgements=sum(cmd['type']=='gains' for cmd in commands),
        all_ki_applied_before_planned_reference_transitions=True,
        minimum_actual_lead_ms=min(p['actual_lead_ms'] for p in proofs),
        telemetry_sha256=hashlib.sha256((trial/'telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((trial/'commands.jsonl').read_bytes()).hexdigest(),
        primary_metric_changed=False, statistical_inference_performed=False,
        td3_training_performed=False, added_to_kp_only_replay=False, actor_applied=False,
        per_packet_stage_journal_present=journal_present,
        ki_action_mask_activated=False, hardware_accessed=False, deployment_allowed=False, performance_claim_allowed=False,
        learning_limitation=('Response audit with complete stage journal; a separate Ki-enabled replay contract and independent validation boots are still required'
            if journal_present else 'Response audit only; this session lacks the per-packet stage-proof stream required by the TD3 importer'))
    out.mkdir(parents=True,exist_ok=False)
    for name,value in [('gain-effect-summary',result),('slot-responses',rows),('gain-application-proofs',proofs)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','contract','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    run(args.trial,args.contract,args.output)
