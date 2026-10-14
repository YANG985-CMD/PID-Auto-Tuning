"""One finite v13 trial with predeclared stratified two-gain excitation.

45 slots of 400ms, stratified by actual firmware reference phase. Schedule
does not observe speed error or Actor output; total and all bounds stay fixed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32

SEED=20261013
START_MS=4000
END_MS=22000
SLOT_MS=400


def schedule(seed=SEED):
    rng=random.Random(seed);values=[None]*45
    for phase in range(3):
        positions=[i for i in range(45) if i%9//3==phase]
        choices=[0]*7+[1]*8
        rng.shuffle(choices)
        for i,value in zip(positions,choices):values[i]=value
    return values


PATTERN=tuple(schedule())


class BalancedProbe:
    def __init__(self):self.decisions=[];self.slot=-1
    def observe(self,t):pass # The reviewed outer guard checks telemetry.
    def planned(self,ms,ki_probe_sign=0,mode='baseline'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported probe')
        if mode=='baseline' or ms<START_MS or ms>=END_MS:return f32(.003389),f32(.00144)
        slot=int((ms-START_MS)//SLOT_MS)
        if slot<self.slot or self.slot>=0 and slot>self.slot+1:raise RuntimeError('Missed planned slot')
        if slot>self.slot:
            self.slot=slot;self.decisions.append(dict(slot=slot,elapsed_ms=ms,planned_high=PATTERN[slot],
                kp=f32(.00352456 if PATTERN[slot] else .003389),ki=f32(.00144)))
        return f32(.00352456 if PATTERN[slot] else .003389),f32(.00144)


def run(a):
    if not getattr(a,'authorized_balanced_probe',False):raise ValueError('Finite balanced excitation scope required')
    a.authorized_continuous=True
    if a.phase not in ('prepare','trial'):raise ValueError('This entry cannot flash')
    contract=Path(a.schedule_contract)
    planned=json.loads(contract.read_text(encoding='utf-8'))
    if (planned['pattern']!=list(PATTERN) or planned['seed']!=SEED or
            planned['maximum_motion_seconds']!=24 or planned['reserved_batch_motion_seconds']!=24 or
            planned['requested_rounds']!=1 or planned['slot_ms']!=SLOT_MS or
            planned['actor_applied'] is not False or planned['training_split']!='training-only'):
        raise ValueError('Unreviewed or changed predeclared probe contract')
    if a.phase=='trial' and Path(a.output).exists():raise ValueError('Consumed motion budget cannot be retried')
    with overrides(continuous,ContinuousProbe=BalancedProbe):result=continuous.run(a)
    result.update(behavior_policy='predeclared-reference-stratified-two-gain-v1',probe_seed=SEED,
        probe_slot_ms=SLOT_MS,probe_pattern=list(PATTERN),schedule_contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
        training_split='training-only',actor_applied=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','nm','schedule-contract'):p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','trainer-ready-file'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='kp_probe')
    for name in ('authorized-balanced-probe','power-disconnected-confirmed','energized-phase-inhibited-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
