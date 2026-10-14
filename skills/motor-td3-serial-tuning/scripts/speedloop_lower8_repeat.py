"""Predeclared two24s independent boots, fresh sampling train/holdout split.

Capture-only: keeps validation out of all online learners. Same exact v19
image, Ki, gain points and stop bounds. No automatic retry after any fault.
"""
import argparse
import json
from pathlib import Path
import random
import speedloop_lower8_response as previous
from speedloop_duration_review import overrides


def schedule(seed):
    if seed not in (20261021,20261022):raise ValueError('Undeclared repeat seed')
    rng=random.Random(seed);order=[0,1,2];rng.shuffle(order)
    shifts=[0,1,2,0,1];rng.shuffle(shifts)
    return tuple(order[(phase+shift)%3] for shift in shifts for phase in range(3))


def run(args):
    batch=json.loads(Path(args.batch_contract).read_text(encoding='utf-8'))
    if (batch.get('reserved_motion_seconds')!=48 or batch.get('requested_rounds')!=2
            or batch.get('round_seeds')!=[20261021,20261022]
            or batch.get('fault_ends_entire_batch') is not True or batch.get('automatic_retry') is not False
            or batch.get('training_boot_indices')!=[0,1] or batch.get('validation_boot_indices')!=[2]):
        raise ValueError('Finite two-round train/holdout contract required')
    if args.round_index==2:
        last=json.loads(Path(args.previous_trial_summary).read_text(encoding='utf-8'))
        if (not last['passed'] or last['final_irq_fault'] or last['final_tx_fault']
                or not last['protocol_stop_acknowledged'] or not last['core_halted_after_physical_shutdown']
                or not last['can_released_after_shutdown']):
            raise ValueError('Prior fault/unfinished shutdown ends entire batch')
    args.capture_only=True;args.trainer_ready_file=None
    seed=20261020+args.round_index
    with overrides(previous,SEED=seed,PATTERN=schedule(seed)):
        result=previous.run(args)
    if args.phase=='trial':
        result.update(capture_only=True,online_training_performed=False,
            predeclared_split='train' if args.round_index==1 else 'validation',
            validation_boot_excluded_from_online_replay=args.round_index==2,
            independent_repeat_index=args.round_index)
        (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','nm','batch-contract'):p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','schedule-contract','previous-trial-summary'):p.add_argument('--'+name)
    p.add_argument('--round-index',type=int,choices=(1,2),required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for name in ('authorized-larger-kp-exploration','energized-phase-inhibited-confirmed',
                 'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.round_index==2 and not a.previous_trial_summary:p.error('Previous physical shutdown evidence required')
    if a.phase=='trial' and not all((a.boot_token_file,a.stream_output,a.schedule_contract)):p.error('Missing capture paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
