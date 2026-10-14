"""SEPARATELY APPROVED one24s baseline/-4% commissioning; never Actor.

Primary operator must obtain human permission before setting the approval
argument. A goal, prior positive-gain scope or a generated plan is insufficient.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_continuous as continuous
import speedloop_interior as predecessor
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32
from speedloop_stream_training import LOWER_GAINS
from build_speedloop_lower_commission import IDENTITY

IMAGE_SHA='6269a6ac7c3eb0855276736d418a20fcb1013fb5de6e7fe4442a62d9fbdfc3d8'
HEX_SHA='ffdf7a1dccb108b1482dd8725ece1b73df79cb664da9e87f7c88d17f644742b3'
IMAGE_BYTES=51116
SEED=20261015


def schedule():
    rng=random.Random(SEED);offsets=[rng.randrange(2) for _ in range(9)]
    # Within every (reference phase, position after reference change) cell,
    # five cycles give two/three exposures per arm, never a missing cell.
    return tuple((i//9+offsets[i%9])%2 for i in range(45))


PATTERN=schedule()


class LowerProbe:
    def __init__(self):self.slot=-1;self.decisions=[]
    def observe(self,t):pass
    def planned(self,ms,ki_probe_sign=0,mode='baseline'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported lower commissioning')
        if mode=='baseline' or ms<4000 or ms>=22000:return f32(.003389),f32(.00144)
        slot=int((ms-4000)//400)
        if slot<self.slot or self.slot>=0 and slot>self.slot+1:raise RuntimeError('Missed declared lower slot')
        kp=f32(.00325344 if PATTERN[slot] else .003389)
        if slot>self.slot:
            self.slot=slot;self.decisions.append(dict(slot=slot,elapsed_ms=ms,lower=PATTERN[slot],kp=kp,ki=f32(.00144)))
        return kp,f32(.00144)


def validate(a):
    if not getattr(a,'operator_approved_lower_probe',False):
        raise ValueError('Direct human authorization for the new lower point is required before any hardware access')
    if not getattr(a,'authorized_lower_commission',False):raise ValueError('Distinct finite lower commissioning scope required')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    p=info.get('lower_commission_proposal',{})
    if (p.get('proposed_kp')!=.00325344 or p.get('fixed_ki')!=.00144 or p.get('actor_allowed') is not False
            or p.get('current_speed_bus_duration_lease_limits_modified') is not False or p.get('maximum_motion_seconds')!=24):
        raise ValueError('Unreviewed lower point or changed protection contract')
    if a.phase=='trial':
        if Path(a.output).exists():raise ValueError('Consumed experiment cannot be retried')
        c=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
        if (c.get('pattern')!=list(PATTERN) or c.get('seed')!=SEED or c.get('reserved_batch_motion_seconds')!=24
                or c.get('requested_rounds')!=1 or c.get('kp_values')!=[.003389,.00325344]
                or c.get('actor_applied') is not False or c.get('operator_approved_lower_probe') is not True
                or c.get('verified_elapsed_since_previous_stop_seconds',0)<30):
            raise ValueError('Missing approved finite schedule or cooldown proof')
    return info


def run(a):
    validate(a);a.stream_gain_levels=LOWER_GAINS
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
        OLD_SHA=predecessor.IMAGE_SHA,OLD_BYTES=predecessor.IMAGE_BYTES,ContinuousProbe=LowerProbe):
        result=continuous.run(a)
    result.update(operator_approved_lower_probe=True,ordinary_policy_gain_envelope_unchanged=True)
    if a.phase=='trial':
        result.update(behavior_policy='reference-position-balanced-baseline-lower-v1',probe_pattern=list(PATTERN),
            probe_seed=SEED,probe_slot_ms=400,exact_kp_levels=[f32(.003389),f32(.00325344)],
            schedule_contract_sha256=hashlib.sha256(Path(a.schedule_contract).read_bytes()).hexdigest(),
            lower_commissioning_trial=True,actor_applied=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','stream-output','trainer-ready-file','schedule-contract'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='kp_probe')
    for name in ('operator-approved-lower-probe','authorized-lower-commission','energized-update-authorized',
        'power-disconnected-confirmed','energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file','schedule_contract','stream_output','trainer_ready_file')}
    if any(not getattr(a,k) for k in needed[a.phase]):p.error('Missing phase paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
