"""Exact v14 commissioning entry: baseline/+2%/+4%, fixed Ki, never Actor.

This is a distinct single24s experiment. v13 tools reject its image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32
from speedloop_stream_training import INTERIOR_GAINS
from build_speedloop_interior import IDENTITY

IMAGE_SHA='7cb189130256902de1daa9bc31d25b17bd61c05fdcd206bb905d42aa6ba20204'
HEX_SHA='3950dc04440f0f484703ea46bd0b368abfcf0607e937bf01d98daf58840c3084'
IMAGE_BYTES=51100
OLD_SHA=continuous.IMAGE_SHA
OLD_BYTES=continuous.IMAGE_BYTES
SEED=20261084


def schedule():
    rng=random.Random(SEED);result=[None]*45
    for phase in range(3):
        slots=[i for i in range(45) if i%9//3==phase]
        labels=[0,1,2]*5;rng.shuffle(labels)
        for i,label in zip(slots,labels):result[i]=label
    return tuple(result)


PATTERN=schedule()


class InteriorProbe:
    def __init__(self):self.slot=-1;self.decisions=[]
    def observe(self,t):pass
    def planned(self,ms,ki_probe_sign=0,mode='baseline'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported interior probe')
        if mode=='baseline' or ms<4000 or ms>=22000:return INTERIOR_GAINS[0],f32(.00144)
        slot=int((ms-4000)//400)
        if slot<self.slot or self.slot>=0 and slot>self.slot+1:raise RuntimeError('Missed planned interior slot')
        if slot>self.slot:
            self.slot=slot;self.decisions.append(dict(slot=slot,elapsed_ms=ms,label=PATTERN[slot],
                kp=INTERIOR_GAINS[PATTERN[slot]],ki=f32(.00144)))
        return INTERIOR_GAINS[PATTERN[slot]],f32(.00144)


def validate(a):
    if not getattr(a,'authorized_interior_commission',False):raise ValueError('Finite midpoint commissioning scope required')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    e=info.get('interior_review',{})
    if (e.get('exact_kp_levels')!=[.003389,.00345678,.00352456] or e.get('fixed_ki')!=.00144
            or e.get('current_speed_bus_duration_lease_limits_modified') is not False or e.get('actor_allowed') is not False):
        raise ValueError('Unreviewed interior commissioning contract')
    if a.phase=='trial':
        if Path(a.output).exists():raise ValueError('Consumed motion budget cannot be retried')
        c=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
        if (c.get('pattern')!=list(PATTERN) or c.get('seed')!=SEED or c.get('requested_rounds')!=1
                or c.get('reserved_batch_motion_seconds')!=24 or c.get('maximum_motion_seconds')!=24
                or c.get('actor_applied') is not False or c.get('exact_kp_levels')!=[.003389,.00345678,.00352456]):
            raise ValueError('Changed predeclared commissioning budget/schedule')
    return info


def run(a):
    validate(a)
    a.stream_gain_levels=INTERIOR_GAINS
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
                   OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,ContinuousProbe=InteriorProbe):
        result=continuous.run(a)
    if a.phase=='trial':
        result.update(behavior_policy='reference-stratified-three-level-commission-v1',probe_pattern=list(PATTERN),
            probe_seed=SEED,exact_kp_levels=list(INTERIOR_GAINS),probe_slot_ms=400,
            schedule_contract_sha256=hashlib.sha256(Path(a.schedule_contract).read_bytes()).hexdigest(),
            midpoint_commissioning_trial=True,actor_applied=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','stream-output','trainer-ready-file','schedule-contract'):p.add_argument('--'+name)
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='kp_probe')
    p.add_argument('--uid',default='0674FF554850715087183841')
    for name in ('authorized-interior-commission','energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file','schedule_contract','stream_output','trainer_ready_file')}
    if any(not getattr(a,k) for k in needed[a.phase]):p.error('Missing required phase path')
    raise SystemExit(0 if run(a)['passed'] else 1)
