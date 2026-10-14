"""Single-boot actual response comparison at baseline/+2%/+4%.

Training-only commissioning data; cannot qualify a new Actor's performance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean
from speedloop_interior import PATTERN,SEED,IDENTITY,IMAGE_SHA
from speedloop_stream_training import INTERIOR_GAINS
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import lines,temporal_mean


def arm_scores(rows):
    mse=[mean(mean(r['response_mse_rpm2'] for r in rows if r['reference_phase']==p and r['level']==g)
              for p in range(3)) for g in range(3)]
    scores=[math.sqrt(v) for v in mse]
    return [dict(level=g,kp=INTERIOR_GAINS[g],rmse_rpm=scores[g],
        rmse_improvement_fraction=(scores[0]-scores[g])/scores[0]) for g in range(3)]


def run(trial,contract,output):
    path,contract,out=map(lambda p:Path(p).resolve(),(trial,contract,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    s=json.loads((path/'summary.json').read_text(encoding='utf-8'));c=json.loads(contract.read_text(encoding='utf-8'))
    if (not s['passed'] or s['actor_applied'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
            or s['probe_pattern']!=list(PATTERN) or c['pattern']!=list(PATTERN)
            or hashlib.sha256(contract.read_bytes()).hexdigest()!=s['schedule_contract_sha256']):
        raise ValueError('Changed predeclaration or unsuccessful physical trial')
    raw=lines(path/'telemetry.jsonl');commands=lines(path/'commands.jsonl');bytime={r['t_us']:r for r in raw}
    if any(r['fault'] for r in raw):raise ValueError('Faulted physical data')
    for cmd in commands:
        if cmd['type']!='gains':continue
        elapsed=bytime[cmd['source_t_us']]['elapsed_ms']
        level=PATTERN[int((elapsed-4000)//400)] if 4000<=elapsed<22000 else 0
        if cmd['kp']!=INTERIOR_GAINS[level] or cmd['ki']!=f32(.00144):raise ValueError('Command differs from declared schedule')
    rows=[]
    for i,level in enumerate(PATTERN):
        start=4000+i*400;end=start+400;kp=INTERIOR_GAINS[level];phase=i%9//3;ref=[1100,900,1000][phase]
        response=[r for r in raw if r['enabled'] and start+120<=r['elapsed_ms']<end-20]
        if len(response)<8 or any(r['kp']!=kp or r['ki']!=f32(.00144) or r['speed_ref']!=ref for r in response):
            raise ValueError('Incomplete response or actual gain/reference mismatch')
        if any(b['seq']!=a['seq']+1 or not 15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(response,response[1:])):
            raise ValueError('Slot has sequence or time gap')
        command=next(c for c in commands if c['type']=='gains' and start<=bytime[c['source_t_us']]['elapsed_ms']<end)
        source=bytime[command['source_t_us']]
        mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],[r['t_us'] for r in response])
        rows.append(dict(slot=i,cycle=i//9,reference_phase=phase,speed_ref_rpm=ref,level=level,actual_kp=kp,
            source_seq=source['seq'],source_error_rpm=source['speed_ref']-source['speed'],
            response_sequences=[r['seq'] for r in response],response_mse_rpm2=mse,
            response_rmse_rpm=math.sqrt(mse),peak_speed_rpm=max(abs(r['speed']) for r in response),
            peak_nominal_current_a=max(r['current'] for r in response)))
    scores=arm_scores(rows);phases=[]
    for p in range(3):
        group=[r for r in rows if r['reference_phase']==p];arms=[]
        for g in range(3):
            arm=[r for r in group if r['level']==g]
            if len(arm)!=5:raise ValueError('Unbalanced predeclared phase')
            arms.append(dict(level=g,slots=len(arm),rmse_rpm=math.sqrt(mean(r['response_mse_rpm2'] for r in arm)),
                mean_peak_nominal_current_a=mean(r['peak_nominal_current_a'] for r in arm),
                mean_peak_speed_rpm=mean(r['peak_speed_rpm'] for r in arm),
                mean_source_error_rpm=mean(r['source_error_rpm'] for r in arm)))
        phases.append(dict(speed_ref_rpm=[1100,900,1000][p],arms=arms))
    rng=random.Random(SEED+1);null=[[],[]]
    for _ in range(3000):
        shuffled=[dict(r) for r in rows]
        for phase in range(3):
            ids=[i for i,r in enumerate(shuffled) if r['reference_phase']==phase]
            values=[shuffled[i]['level'] for i in ids];rng.shuffle(values)
            for i,v in zip(ids,values):shuffled[i]['level']=v
        score=arm_scores(shuffled)
        for j in range(2):null[j].append(score[j+1]['rmse_rpm']-score[0]['rmse_rpm'])
    pvalues=[(1+sum(abs(x)>=abs(scores[j+1]['rmse_rpm']-scores[0]['rmse_rpm']) for x in null[j]))/3001 for j in range(2)]
    result=dict(source='single_real_motor_three_level_commission',boot_id=raw[0]['boot_id'],slots=45,
        arms=scores,reference_phases=phases,randomization_two_sided_p_mid_high=pvalues,
        randomization_assumption='Exploratory sharp no-effect/no-carryover null; single boot; no independent Actor repeats',
        score_window_ms_relative_to_slot=[120,380],phase_equal_weight=True,actor_applied=False,
        midpoint_actual_gain_readback_verified=True,hardware_accessed=False,
        telemetry_sha256=hashlib.sha256((path/'telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((path/'commands.jsonl').read_bytes()).hexdigest(),
        contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
        actor_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    out.mkdir(parents=True,exist_ok=False)
    (out/'slot-responses.json').write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (out/'gain-effect-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','contract','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.trial,a.contract,a.output)
