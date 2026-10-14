"""Actual slot response analysis for one predeclared stratified gain trial.

Single-boot exploratory comparisons never grant Actor admission/deployment.
The randomization diagnostic is conditional on a no-effect/no-carryover null.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean
from speedloop_balanced_probe import PATTERN,SEED,SLOT_MS
from speedloop_response_windows import lines,temporal_mean
from speedloop_motion_gain_trial import f32


def effect(slots,labels):
    high=[];low=[]
    for phase in range(3):
        group=[(r,v) for r,v in zip(slots,labels) if r['reference_phase']==phase]
        high.append(mean(r['response_mse_rpm2'] for r,v in group if v))
        low.append(mean(r['response_mse_rpm2'] for r,v in group if not v))
    h,l=math.sqrt(mean(high)),math.sqrt(mean(low))
    return dict(baseline_rmse_rpm=l,probe_rmse_rpm=h,rmse_improvement_fraction=(l-h)/l,
                phase_equal_weight_mse_difference=mean(high)-mean(low))


def run(trial,contract,output):
    path,contract,out=map(lambda p:Path(p).resolve(),(trial,contract,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    s=json.loads((path/'summary.json').read_text(encoding='utf-8'));c=json.loads(contract.read_text(encoding='utf-8'))
    if not s['passed'] or s['actor_applied'] or s['probe_pattern']!=list(PATTERN) or c['pattern']!=list(PATTERN):
        raise ValueError('Changed schedule or failed trial')
    if hashlib.sha256(contract.read_bytes()).hexdigest()!=s['schedule_contract_sha256']:raise ValueError('Predeclared contract changed')
    t=lines(path/'telemetry.jsonl');commands=lines(path/'commands.jsonl');bytime={r['t_us']:r for r in t}
    if any(r['fault'] for r in t):raise ValueError('Faulted physical data')
    # Independently verify every actual command's planned source-time action.
    for cmd in commands:
        if cmd['type']!='gains':continue
        source=bytime[cmd['source_t_us']];elapsed=source['elapsed_ms']
        slot=int((elapsed-4000)//SLOT_MS)
        high=4000<=elapsed<22000 and PATTERN[slot]
        expected=f32(.00352456 if high else .003389)
        if cmd['kp']!=expected or cmd['ki']!=f32(.00144):raise ValueError('Action differs from predeclaration')
    slots=[]
    for i,label in enumerate(PATTERN):
        start=4000+i*SLOT_MS;end=start+SLOT_MS;kp=f32(.00352456 if label else .003389)
        # Discard the first120ms of every slot identically, including holds.
        response=[r for r in t if r['enabled'] and start+120<=r['elapsed_ms']<end-20]
        if len(response)<8 or any(r['kp']!=kp or r['ki']!=f32(.00144) for r in response):
            raise ValueError('Missing late response or actual gain did not match slot')
        if any(b['seq']!=a['seq']+1 or not 15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(response,response[1:])):
            raise ValueError('Slot has telemetry gaps')
        phase=i%9//3;reference=[1100,900,1000][phase]
        if any(r['speed_ref']!=reference for r in response):raise ValueError('Different reference in slot')
        source_cmd=next(cmd for cmd in commands if cmd['type']=='gains' and start<=bytime[cmd['source_t_us']]['elapsed_ms']<end)
        source=bytime[source_cmd['source_t_us']];before=[r for r in t if r['seq'] in (source['seq']-2,source['seq']-1,source['seq'])]
        mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],[r['t_us'] for r in response])
        slots.append(dict(slot=i,cycle=i//9,reference_phase=phase,speed_ref_rpm=reference,high_kp=label,
            actual_kp=kp,first_source_seq=source['seq'],source_error_rpm=source['speed_ref']-source['speed'],
            three_source_errors_rpm=[r['speed_ref']-r['speed'] for r in before],
            source_mean_error_rpm=mean(r['speed_ref']-r['speed'] for r in before),
            response_sequences=[r['seq'] for r in response],response_mse_rpm2=mse,
            response_rmse_rpm=math.sqrt(mse),peak_nominal_current_a=max(r['current'] for r in response),
            peak_speed_rpm=max(abs(r['speed']) for r in response)))
    result=effect(slots,PATTERN);perphase=[]
    for phase in range(3):
        group=[r for r in slots if r['reference_phase']==phase]
        high=[r for r in group if r['high_kp']];low=[r for r in group if not r['high_kp']]
        h,l=math.sqrt(mean(r['response_mse_rpm2'] for r in high)),math.sqrt(mean(r['response_mse_rpm2'] for r in low))
        perphase.append(dict(speed_ref_rpm=[1100,900,1000][phase],baseline_slots=len(low),probe_slots=len(high),
            baseline_rmse_rpm=l,probe_rmse_rpm=h,rmse_improvement_fraction=(l-h)/l,
            baseline_mean_peak_current_a=mean(r['peak_nominal_current_a'] for r in low),
            probe_mean_peak_current_a=mean(r['peak_nominal_current_a'] for r in high),
            baseline_source_mean_error_rpm=mean(r['source_mean_error_rpm'] for r in low),
            probe_source_mean_error_rpm=mean(r['source_mean_error_rpm'] for r in high)))
    rng=random.Random(SEED+1);null=[]
    for _ in range(3000):
        labels=list(PATTERN)
        for phase in range(3):
            ids=[i for i,r in enumerate(slots) if r['reference_phase']==phase]
            values=[labels[i] for i in ids];rng.shuffle(values)
            for i,v in zip(ids,values):labels[i]=v
        null.append(effect(slots,labels)['phase_equal_weight_mse_difference'])
    p=(1+sum(abs(v)>=abs(result['phase_equal_weight_mse_difference']) for v in null))/(len(null)+1)
    result.update(schema_version=1,source='one_real_motor_stratified_gain_trial',boot_id=t[0]['boot_id'],
        slots=len(slots),reference_phases=perphase,hardware_accessed=False,actor_applied=False,
        randomization_two_sided_p=p,randomization_draws=len(null),
        randomization_assumption='Sharp no-treatment-effect and no-carryover null; exploratory single-boot diagnostic',
        score_window_ms_relative_to_slot=[120,380],phase_equal_weight=True,
        independent_physical_actor_repeats=0,training_split='training-only',
        telemetry_sha256=hashlib.sha256((path/'telemetry.jsonl').read_bytes()).hexdigest(),
        commands_sha256=hashlib.sha256((path/'commands.jsonl').read_bytes()).hexdigest(),
        contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
        actor_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    out.mkdir(parents=True,exist_ok=False)
    (out/'slot-responses.json').write_text(json.dumps(slots,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (out/'gain-effect-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','contract','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.trial,a.contract,a.output)
