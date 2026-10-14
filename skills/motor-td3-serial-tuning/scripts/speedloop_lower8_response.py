"""One24s exact baseline/-4%/-7.9% trial; fixed Ki, real training stream.

New scope comes from direct human authorization for continued larger Kp/Ki
exploration. Learner candidates remain separate from physical commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32
from speedloop_stream_training import LOWER8_GAINS
from speedloop_sampling_response import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES
from build_speedloop_lower8_review import IDENTITY

IMAGE_SHA='12ea1aef08224c6e29429bcda7a6b727a188c7e9d858fb53e4384704afcc6928'
HEX_SHA='711c0f6bfd20436fafd46707a7ad3b1d8eb59606148f5cafd9020153a932f039'
IMAGE_BYTES=51232
KP_LEVELS=tuple(map(f32,(.003389,.00325344,.003121269)))
SEED=20261020
SEGMENT_MS=1200
LEAD_MS=150


def schedule():
    rng=random.Random(SEED);order=[0,1,2];rng.shuffle(order)
    shifts=[0,1,2,0,1];rng.shuffle(shifts)
    return tuple(order[(phase+shift)%3] for shift in shifts for phase in range(3))


PATTERN=schedule()


class Lower8Probe:
    def __init__(self):self.segment=-1;self.decisions=[]
    def observe(self,t):pass
    def planned(self,elapsed,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode!='kp_probe':raise ValueError('Fixed-Ki lower8 experiment required')
        if elapsed<3850 or elapsed>=22000:return KP_LEVELS[0],f32(.00144)
        segment=min(14,int((elapsed+LEAD_MS-4000)//SEGMENT_MS))
        if segment<self.segment or self.segment>=0 and segment>self.segment+1:
            raise RuntimeError('Missed declared lower8 segment')
        if segment>self.segment:
            self.segment=segment;self.decisions.append(dict(segment=segment,source_elapsed_ms=elapsed,
                level=PATTERN[segment],kp=KP_LEVELS[PATTERN[segment]],ki=f32(.00144)))
        return KP_LEVELS[PATTERN[segment]],f32(.00144)


def validate(args):
    if not getattr(args,'authorized_larger_kp_exploration',False):
        raise ValueError('Direct human authorization for continued larger exploration required')
    args.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        result=continuous.validate(args)
    review=result.get('lower8_review',{})
    if (review.get('exact_kp_levels')!=[.003389,.00325344,.003121269]
            or review.get('fixed_ki')!=.00144 or review.get('maximum_motion_seconds')!=24
            or review.get('current_speed_bus_duration_lease_limits_modified') is not False
            or review.get('actor_allowed') is not False or review.get('thermal_gate_modified') is not False):
        raise ValueError('Changed exact Kp or protection contract')
    if args.phase=='trial':
        if Path(args.output).exists():raise ValueError('Consumed trial cannot be retried')
        c=json.loads(Path(args.schedule_contract).read_text(encoding='utf-8'))
        if (c.get('pattern')!=list(PATTERN) or c.get('seed')!=SEED
                or c.get('reserved_motion_seconds')!=24 or c.get('requested_rounds')!=1
                or c.get('exact_kp_levels')!=list(KP_LEVELS) or c.get('fixed_ki')!=f32(.00144)
                or c.get('actor_applied') is not False or c.get('fault_automatic_retry') is not False
                or c.get('verified_cooldown_seconds',0)<30
                or c.get('reference_position_evaluation_ms')!=[[100,260],[500,660],[900,1000]]):
            raise ValueError('Missing finite predeclared lower8 schedule/cooldown')
    return result


def run(args):
    validate(args);args.stream_gain_levels=LOWER8_GAINS
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
                   OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,ContinuousProbe=Lower8Probe):
        result=continuous.run(args)
    if args.phase=='trial':
        result.update(behavior_policy='full-reference-segment-lower8-v1',probe_segment_ms=SEGMENT_MS,
            probe_lead_ms=LEAD_MS,probe_pattern=list(PATTERN),probe_seed=SEED,
            exact_kp_levels=list(KP_LEVELS),fixed_ki=f32(.00144),larger_kp_exploration_authorized=True,
            action_envelope_expansion_is_experimental=True,actor_applied=False,
            schedule_contract_sha256=hashlib.sha256(Path(args.schedule_contract).read_bytes()).hexdigest())
        (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','stream-output','trainer-ready-file','schedule-contract'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--gain-mode',choices=('kp_probe',),default='kp_probe')
    for name in ('authorized-larger-kp-exploration','energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file','schedule_contract','stream_output','trainer_ready_file')}
    if any(not getattr(a,k) for k in needed[a.phase]):p.error('Missing phase paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
