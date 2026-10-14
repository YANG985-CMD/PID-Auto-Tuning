"""State-conditioned two-gain exploration on the exact v12 image.

250ms decision slots, baseline/+4% only, three real telemetry errors.
This behavior policy collects TD3 experience; it is not an Actor or benchmark.
No flash, new gains, changed deadline, Ki, references, or protection limits.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import speedloop_excitation_evidence as review
import speedloop_excitation_review as excitation
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32

BASE_CHECK=excitation.check_telemetry


class ReactiveProbe:
    def __init__(self):
        self.history=deque(maxlen=3);self.slot=-1;self.high=False;self.decisions=[]

    def observe(self,obj):
        if not obj['enabled']:return
        if self.history:
            old=self.history[-1]
            if obj['seq']!=old['seq']+1 or not 15000<=obj['t_us']-old['t_us']<=25000:
                raise RuntimeError('Reactive history frame gap')
        self.history.append(dict(seq=obj['seq'],t_us=obj['t_us'],elapsed_ms=obj['elapsed_ms'],
            error=obj['speed_ref']-obj['speed']))

    def planned(self,elapsed_ms,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported reactive action')
        if mode=='baseline' or elapsed_ms<3900 or elapsed_ms>=6900:
            return f32(.003389),f32(.00144)
        if len(self.history)!=3 or self.history[-1]['elapsed_ms']!=elapsed_ms:
            raise RuntimeError('Missing causal history for gain decision')
        slot=int((elapsed_ms-3900)//250)
        if slot<self.slot:raise RuntimeError('Reactive clock regression')
        if slot>self.slot:
            if self.slot>=0 and slot!=self.slot+1:raise RuntimeError('Missed reactive decision slot')
            error=sum(p['error'] for p in self.history)/3
            if error<-20:self.high=True
            elif error>=0:self.high=False
            self.slot=slot
            self.decisions.append(dict(slot=slot,elapsed_ms=elapsed_ms,
                source_sequences=[p['seq'] for p in self.history],
                source_t_us=[p['t_us'] for p in self.history],mean_error_rpm=error,
                kp=f32(.00352456 if self.high else .003389),ki=f32(.00144)))
        return f32(.00352456 if self.high else .003389),f32(.00144)


def validate(a):
    if not getattr(a,'authorized_reactive_probe',False):raise ValueError('Bounded reactive exploration scope required')
    a.authorized_excitation_evidence=True
    return review.validate(a)


def run(a):
    validate(a)
    if a.phase not in ('prepare','trial'):raise ValueError('Reactive probe cannot flash')
    policy=ReactiveProbe()
    def check(obj,last,sent):
        BASE_CHECK(obj,last,sent);policy.observe(obj)
    with overrides(excitation,planned_gains=policy.planned,check_telemetry=check):
        result=review.run(a)
    if a.phase=='trial':
        mode=getattr(a,'gain_mode','baseline')
        result.update(gain_mode='reactive_probe' if mode=='kp_probe' else 'baseline',
            runtime_profile='250ms-reactive-two-gain-exploration-v1',
            behavior_policy='three prior/current telemetry errors; high below -20rpm, baseline at nonnegative mean error',
            decision_slot_ms=250,probe_source_elapsed_ms=[3900,6900],actor_applied=False,
            policy_decisions=len(policy.decisions),
            runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (Path(a.output)/'reactive-decisions.json').write_text(json.dumps(policy.decisions,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-reactive-probe',action='store_true')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    p.add_argument('--boot-token-file')
    for name in ('energized-phase-inhibited-confirmed','power-disconnected-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.phase=='trial' and not a.boot_token_file:p.error('Boot token required')
    raise SystemExit(0 if run(a)['passed'] else 1)
