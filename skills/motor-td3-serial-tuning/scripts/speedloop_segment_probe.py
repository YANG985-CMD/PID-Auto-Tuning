"""Existing v14 gains held across full reference segments; no range expansion.

Five cycles,15 reference segments. Each cycle uses all3 exact gains once.
Apply150ms before the known reference transition; no future motor measurement.
One24s experiment must be predeclared; no Actor, flash or consumed-budget retry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_interior as interior
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_stream_training import INTERIOR_GAINS
from speedloop_motion_gain_trial import f32

SEED=20261016
SEGMENT_MS=1200
LEAD_MS=150


def schedule():
    rng=random.Random(SEED);permutation=[0,1,2];rng.shuffle(permutation)
    return tuple(permutation[(cycle+phase)%3] for cycle in range(5) for phase in range(3))


PATTERN=schedule()


class SegmentProbe:
    def __init__(self):self.segment=-1;self.decisions=[]
    def observe(self,t):pass
    def planned(self,ms,ki_probe_sign=0,mode='baseline'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported segment commissioning')
        if mode=='baseline' or ms<3850 or ms>=22000:return INTERIOR_GAINS[0],f32(.00144)
        segment=min(14,int((ms+LEAD_MS-4000)//SEGMENT_MS))
        if segment<self.segment or self.segment>=0 and segment>self.segment+1:
            raise RuntimeError('Missed predeclared segment')
        if segment>self.segment:
            self.segment=segment;self.decisions.append(dict(segment=segment,source_elapsed_ms=ms,
                planned_reference_begin_ms=4000+segment*SEGMENT_MS,planned_reference_rpm=[1100,900,1000][segment%3],
                known_reference_schedule_used=True,no_future_motor_measurements=True,
                level=PATTERN[segment],kp=INTERIOR_GAINS[PATTERN[segment]],ki=f32(.00144)))
        return INTERIOR_GAINS[PATTERN[segment]],f32(.00144)


def run(a):
    if not getattr(a,'authorized_segment_probe',False):raise ValueError('Distinct one24s segment scope required')
    if a.phase not in ('prepare','trial'):raise ValueError('Segment entry cannot flash')
    contract=Path(a.schedule_contract)
    c=json.loads(contract.read_text(encoding='utf-8'))
    if (c.get('pattern')!=list(PATTERN) or c.get('seed')!=SEED or c.get('segment_ms')!=SEGMENT_MS
        or c.get('lead_ms')!=LEAD_MS or c.get('requested_rounds')!=1 or c.get('maximum_motion_seconds')!=24
        or c.get('reserved_batch_motion_seconds')!=24 or c.get('actor_applied') is not False
        or c.get('exact_kp_levels')!=[.003389,.00345678,.00352456]
        or c.get('verified_elapsed_since_previous_stop_seconds',0)<30):
        raise ValueError('Changed segment plan, boundary, budget or cooldown')
    a.authorized_interior_commission=True
    with overrides(interior,PATTERN=PATTERN,SEED=SEED,InteriorProbe=SegmentProbe):
        result=interior.run(a)
    if a.phase=='trial':
        result.update(behavior_policy='full-reference-segment-three-gain-v1',probe_segment_ms=SEGMENT_MS,
            probe_lead_ms=LEAD_MS,probe_pattern=list(PATTERN),probe_seed=SEED,probe_slot_ms=None,
            reference_future_is_known_exogenous_plan=True,motor_future_observation_used=False,
            operator_lower_probe_approval_required=False,gain_envelope_expanded=False,
            schedule_contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest())
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','nm','schedule-contract'):p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','trainer-ready-file'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='kp_probe')
    for name in ('authorized-segment-probe','energized-phase-inhibited-confirmed','power-disconnected-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.phase=='trial' and not all((a.boot_token_file,a.stream_output,a.trainer_ready_file)):p.error('Missing live stream paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
