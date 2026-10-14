"""Actual applied-gain fixed-reference response audit; no counterfactual claim."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from speedloop_fixedref_probe import IDENTITY,IMAGE_SHA,KP_LEVELS,schedule
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import temporal_mean


def run(folder,contract,output):
    folder,contract,output=map(lambda p:Path(p).resolve(),(folder,contract,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents or output.exists():raise ValueError('New temporary output required')
    s=json.loads((folder/'trial/summary.json').read_text(encoding='utf-8'));c=json.loads(contract.read_text(encoding='utf-8'))
    if (not s['passed'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
        or s['actor_applied'] or s['probe_pattern']!=list(schedule(c['seed']))
        or hashlib.sha256(contract.read_bytes()).hexdigest()!=s['schedule_contract_sha256']
        or c['evaluation_after_first_actual_apply_ms']!=[120,300]):raise ValueError('Changed trial/contract')
    raw=[json.loads(l) for l in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
    commands=[json.loads(l) for l in (folder/'trial/commands.jsonl').read_text().splitlines()]
    if len({r['boot_id'] for r in raw})!=1 or any(r['fault'] or r['enabled'] and r['speed_ref']!=1000 for r in raw):
        raise ValueError('Different boot, fault or nonconstant reference')
    bytime={r['t_us']:r for r in raw};grouped={i:[] for i in range(45)}
    for cmd in commands:
        if cmd['type']!='gains':continue
        source=bytime[cmd['source_t_us']];ms=source['elapsed_ms'];level=0
        if 4000<=ms<22000:
            slot=int((ms-4000)//400);level=c['pattern'][slot];grouped[slot].append(cmd)
        if (cmd['kp'],cmd['ki'])!=(KP_LEVELS[level],f32(.00144)):raise ValueError('Action differs from declared schedule')
        ack=[r for r in raw if r['applied_seq']==cmd['command_seq']]
        if not ack or any((r['kp'],r['ki'])!=(cmd['kp'],cmd['ki']) or not cmd['source_t_us']<r['t_apply_us']<=cmd['expires_us'] for r in ack):
            raise ValueError('Actual gain ACK missing/mismatched')
    rows=[];pairs=Counter()
    for slot in range(45):
        first=grouped[slot][0];source=bytime[first['source_t_us']]
        old=0 if slot==0 else c['pattern'][slot-1];new=c['pattern'][slot]
        if source['kp']!=KP_LEVELS[old]:raise ValueError('Previous gain differs from transition plan')
        ack=next(r for r in raw if r['applied_seq']==first['command_seq']);effective=ack['t_apply_us']
        response=[r for r in raw if r['enabled'] and effective+120000<=r['t_us']<effective+300000]
        if (len(response)<7 or any(r['kp']!=KP_LEVELS[new] or r['ki']!=f32(.00144) for r in response)
            or any(b['seq']!=a['seq']+1 for a,b in zip(response,response[1:]))):raise ValueError('Incomplete held-action response')
        mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],[r['t_us'] for r in response])
        pairs[(old,new)]+=1;rows.append(dict(slot=slot,from_level=old,to_level=new,
            source_seq=source['seq'],actual_command_seq=first['command_seq'],actual_apply_us=effective,
            response_sequences=[r['seq'] for r in response],response_mse_rpm2=mse,
            peak_nominal_current_a=max(r['current'] for r in response),peak_speed_rpm=max(r['speed'] for r in response)))
    if any(pairs[(i,j)]!=5 for i in range(3) for j in range(3)):raise ValueError('Incomplete actual pair coverage')
    scores=[]
    for new in range(3):
        cells=[[r for r in rows if r['from_level']==old and r['to_level']==new] for old in range(3)]
        scores.append(dict(level=new,actual_kp=KP_LEVELS[new],rmse_rpm=math.sqrt(mean(mean(r['response_mse_rpm2'] for r in cell) for cell in cells)),
            mean_peak_nominal_current_a=mean(mean(r['peak_nominal_current_a'] for r in cell) for cell in cells),
            mean_peak_speed_rpm=mean(mean(r['peak_speed_rpm'] for r in cell) for cell in cells)))
    for score in scores:
        score['rmse_improvement_fraction']=1-score['rmse_rpm']/scores[0]['rmse_rpm']
        score['peak_current_difference_a']=score['mean_peak_nominal_current_a']-scores[0]['mean_peak_nominal_current_a']
        score['peak_speed_difference_rpm']=score['mean_peak_speed_rpm']-scores[0]['mean_peak_speed_rpm']
        score['descriptive_thresholds_met']=score['rmse_improvement_fraction']>=.05 and score['peak_current_difference_a']<=0 and score['peak_speed_difference_rpm']<=0
    report=dict(source='actual-fixed-reference-balanced-action-pairs',boot_id=raw[0]['boot_id'],reference_rpm=1000,
        actual_source_to_action_counts=[[pairs[(i,j)] for j in range(3)] for i in range(3)],scores=scores,
        response_definition='120..300ms after first actual gain application in each400ms slot',
        scoring_changed_from_reference_step_study=True,score_basis='Equal weights over previous-gain contexts; single boot descriptive only',
        telemetry_sha256=hashlib.sha256((folder/'trial/telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((folder/'trial/commands.jsonl').read_bytes()).hexdigest(),
        actor_applied=False,deployment_allowed=False,performance_claim_allowed=False,physical_counterfactuals_measured=False)
    output.mkdir(parents=True)
    for name,value in [('fixedref-summary',report),('slot-responses',rows)]:
        (output/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('folder','contract','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.folder,a.contract,a.output)
