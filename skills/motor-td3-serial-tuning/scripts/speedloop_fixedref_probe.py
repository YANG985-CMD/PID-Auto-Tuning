"""Finite fixed1000rpm capture with all nine previous/action pairs balanced.

Two24s boots maximum, first train/second validation, no Actor. A failure ends
the entire batch. Capture-only stage proofs permit later MATLAB training.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_lower8_response import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES,KP_LEVELS
from speedloop_motion_gain_trial import f32
from speedloop_stream_training import LOWER8_GAINS
from build_speedloop_fixedref_review import IDENTITY

IMAGE_SHA='bffea521fbdd184540b01afc8a52d20865790bf54cb97a58d94278702011311b'
HEX_SHA='074d86008d05b2c7aca3d64469305aff98ee74c268649aea0153cfd608a45891'
IMAGE_BYTES=51120
SEEDS=(20261023,20261024)


def schedule(seed):
    if seed not in SEEDS:raise ValueError('Undeclared fixed-reference seed')
    rng=random.Random(seed);graph={i:[j for j in range(3) for _ in range(5)] for i in range(3)}
    for successors in graph.values():rng.shuffle(successors)
    stack=[0];path=[]
    while stack:
        if graph[stack[-1]]:stack.append(graph[stack[-1]].pop())
        else:path.append(stack.pop())
    pattern=tuple(reversed(path))[1:]
    counts=Counter(zip((0,*pattern[:-1]),pattern))
    if len(pattern)!=45 or pattern[-1]!=0 or any(counts[(i,j)]!=5 for i in range(3) for j in range(3)):
        raise ValueError('Incomplete directed transition schedule')
    return pattern


class FixedProbe:
    def __init__(self,seed):self.pattern=schedule(seed);self.slot=-1;self.decisions=[]
    def observe(self,t):pass
    def planned(self,elapsed,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode!='kp_probe':raise ValueError('Only fixed-Ki prescribed Kp capture')
        if elapsed<4000 or elapsed>=22000:return KP_LEVELS[0],f32(.00144)
        slot=int((elapsed-4000)//400)
        if slot<self.slot or self.slot>=0 and slot>self.slot+1:raise RuntimeError('Missed fixed-reference slot')
        if slot>self.slot:
            self.slot=slot;self.decisions.append(dict(slot=slot,source_elapsed_ms=elapsed,
                level=self.pattern[slot],kp=KP_LEVELS[self.pattern[slot]],ki=f32(.00144)))
        return KP_LEVELS[self.pattern[slot]],f32(.00144)


def validate(args):
    if not getattr(args,'authorized_fixedref_capture',False):raise ValueError('Human continued-exploration authorization required')
    args.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(args)
    r=info.get('fixedref_review',{})
    if (r.get('reference_rpm')!=1000 or r.get('fixed_ki')!=.00144
        or r.get('exact_kp_levels')!=[.003389,.00325344,.003121269]
        or r.get('current_speed_bus_duration_lease_limits_modified') is not False
        or r.get('actor_allowed') is not False or r.get('thermal_gate_modified') is not False):
        raise ValueError('Changed fixed-reference physical contract')
    if args.phase!='flash':
        b=json.loads(Path(args.batch_contract).read_text(encoding='utf-8'))
        if (b.get('requested_rounds')!=2 or b.get('maximum_batch_motion_seconds')!=48
            or b.get('round_seeds')!=list(SEEDS) or b.get('fault_ends_entire_batch') is not True
            or b.get('automatic_retry') is not False or b.get('split')!=['train','validation']):
            raise ValueError('Predeclared two-round finite train/validation contract required')
        if args.round_index==1:
            old=json.loads(Path(args.previous_trial_summary).read_text(encoding='utf-8'))
            if (not old['passed'] or old['final_irq_fault'] or old['final_tx_fault']
                or not old['protocol_stop_acknowledged'] or not old['can_released_after_shutdown']):
                raise ValueError('Prior fault ends batch; no automatic retry')
    if args.phase=='trial':
        if Path(args.output).exists():raise ValueError('Consumed round cannot be repeated')
        c=json.loads(Path(args.schedule_contract).read_text(encoding='utf-8'));seed=SEEDS[args.round_index]
        if (c.get('pattern')!=list(schedule(seed)) or c.get('seed')!=seed
            or c.get('reference_rpm')!=1000 or c.get('slot_ms')!=400 or c.get('requested_rounds')!=1
            or c.get('reserved_motion_seconds')!=24 or c.get('exact_kp_levels')!=list(KP_LEVELS)
            or c.get('fixed_ki')!=f32(.00144) or c.get('verified_cooldown_seconds',0)<30
            or c.get('actor_applied') is not False or c.get('fault_automatic_retry') is not False
            or c.get('split')!=['train','validation'][args.round_index]):
            raise ValueError('Changed fixed-reference schedule, split or cooldown')
    return info


def run(args):
    validate(args);args.stream_gain_levels=LOWER8_GAINS;args.capture_only=True;args.trainer_ready_file=None
    seed=SEEDS[getattr(args,'round_index',0)]
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
                   OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,ContinuousProbe=lambda:FixedProbe(seed),
                   reference_matches=lambda ms,ref:ref==1000):
        result=continuous.run(args)
    if args.phase=='trial':
        result.update(probe_pattern=list(schedule(seed)),probe_seed=seed,probe_slot_ms=400,
            exact_kp_levels=list(KP_LEVELS),fixed_ki=f32(.00144),fixed_reference_rpm=1000,
            behavior_policy='balanced-directed-pairs-fixed-reference-v1',capture_only=True,
            online_training_performed=False,predeclared_split=['train','validation'][args.round_index],
            schedule_contract_sha256=hashlib.sha256(Path(args.schedule_contract).read_bytes()).hexdigest(),
            batch_contract_sha256=hashlib.sha256(Path(args.batch_contract).read_bytes()).hexdigest())
        (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','stream-output','schedule-contract','batch-contract','previous-trial-summary'):p.add_argument('--'+name)
    p.add_argument('--round-index',type=int,choices=(0,1),default=0)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for name in ('authorized-fixedref-capture','energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();needed={'flash':('pyocd','pack'),'prepare':('nm','batch_contract'),'trial':('nm','batch_contract','boot_token_file','stream_output','schedule_contract')}
    if any(not getattr(a,n) for n in needed[a.phase]) or a.round_index==1 and not a.previous_trial_summary:p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
