"""Actual matched-position responses with pre-positioned v14 gain levels.

Reference plans may be known in advance; motor responses are always recorded.
Single-boot descriptive evidence is never an independent Actor performance test.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from speedloop_segment_probe import PATTERN,SEED,LEAD_MS,SEGMENT_MS
from speedloop_interior import IDENTITY,IMAGE_SHA
from speedloop_stream_training import INTERIOR_GAINS
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import lines,temporal_mean
from audit_speedloop_context_support import analyze
from speedloop_context_metrics import matched_metrics


def run(trial,contract,output):
    trial,contract,out=map(lambda p:Path(p).resolve(),(trial,contract,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    s=json.loads((trial/'summary.json').read_text(encoding='utf-8'));c=json.loads(contract.read_text(encoding='utf-8'))
    if (not s['passed'] or s['actor_applied'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
        or s['probe_pattern']!=list(PATTERN) or c['pattern']!=list(PATTERN)
        or c['reference_position_evaluation_ms']!=[[100,260],[500,660],[900,1000]]
        or hashlib.sha256(contract.read_bytes()).hexdigest()!=s['schedule_contract_sha256']):
        raise ValueError('Changed predeclared schedule or failed physical trial')
    raw=lines(trial/'telemetry.jsonl');commands=lines(trial/'commands.jsonl');bytime={r['t_us']:r for r in raw}
    if any(r['fault'] for r in raw):raise ValueError('Faulted physical data')
    grouped={i:[] for i in range(15)}
    for cmd in commands:
        if cmd['type']!='gains':continue
        elapsed=bytime[cmd['source_t_us']]['elapsed_ms']
        if 3850<=elapsed<22000:
            segment=min(14,int((elapsed+LEAD_MS-4000)//SEGMENT_MS));grouped[segment].append(cmd);level=PATTERN[segment]
        else:level=0
        if cmd['kp']!=INTERIOR_GAINS[level] or cmd['ki']!=f32(.00144):raise ValueError('Actual command differs from declared schedule')
    proofs=[];rows=[]
    for segment,level in enumerate(PATTERN):
        start=4000+segment*SEGMENT_MS;phase=segment%3;ref=[1100,900,1000][phase]
        first=grouped[segment][0]
        ack=next(r for r in raw if r['applied_seq']==first['command_seq'])
        planned_us=s['trial_timing']['started_us']+start*1000
        lead=(planned_us-ack['t_apply_us'])/1000
        if lead<=0 or ack['kp']!=INTERIOR_GAINS[level]:raise ValueError('Gain was not read back before planned reference transition')
        proofs.append(dict(segment=segment,level=level,command_seq=first['command_seq'],
            actual_t_apply_us=ack['t_apply_us'],planned_reference_t_us=planned_us,actual_lead_ms=lead))
        for position,(lo,hi) in enumerate(c['reference_position_evaluation_ms']):
            response=[r for r in raw if r['enabled'] and start+lo<=r['elapsed_ms']<start+hi]
            if len(response)<4 or any(r['kp']!=INTERIOR_GAINS[level] or r['speed_ref']!=ref for r in response):
                raise ValueError('Missing actual matched-position response or wrong gain/reference')
            if any(b['seq']!=a['seq']+1 or not 15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(response,response[1:])):
                raise ValueError('Response sequence/time gap')
            mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],[r['t_us'] for r in response])
            first_response=response[0]
            rows.append(dict(slot=segment*3+position,segment=segment,cycle=segment//3,reference_phase=phase,
                speed_ref_rpm=ref,level=level,actual_kp=INTERIOR_GAINS[level],response_mse_rpm2=mse,
                source_error_rpm=first_response['speed_ref']-first_response['speed'],
                source_error_basis='First actual response packet at this evaluation position',
                response_sequences=[r['seq'] for r in response],
                peak_nominal_current_a=max(r['current'] for r in response),peak_speed_rpm=max(abs(r['speed']) for r in response)))
    support=analyze(rows)
    if not support['all_gain_levels_supported_in_all_contexts']:raise ValueError('Context hole remains')
    result=dict(source='real_motor_prepositioned_segment_responses',boot_id=raw[0]['boot_id'],
        reference_segments=15,matched_position_cells=45,independent_boots=1,actor_applied=False,
        minimum_actual_gain_lead_ms=min(p['actual_lead_ms'] for p in proofs),
        maximum_actual_gain_lead_ms=max(p['actual_lead_ms'] for p in proofs),
        gain_applied_before_all_planned_reference_transitions=True,context_support=support,
        context_standardized_metrics=matched_metrics(rows,(0,1,2)),
        score_window_definition=c['reference_position_evaluation_ms'],
        comparator_changed_from_400ms_slot_experiment=True,primary_metric_changed=False,
        future_motor_observation_used=False,hardware_accessed=False,
        randomization_significance_test_performed=False,
        statistical_note='15 gain-assigned segments, not45 independent observations; only6 global assignment permutations',
        telemetry_sha256=hashlib.sha256((trial/'telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((trial/'commands.jsonl').read_bytes()).hexdigest(),
        actor_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    out.mkdir(parents=True,exist_ok=False)
    for name,value in [('gain-effect-summary',result),('slot-responses',rows),('gain-application-proofs',proofs)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','contract','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.trial,a.contract,a.output)
