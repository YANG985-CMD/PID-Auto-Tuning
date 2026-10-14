"""Collect alternating measured Kp targets on the exact v12 image.

Only baseline/+4%, fixed Ki, 250ms slots in 3.9..6.9s. No Actor, new gains,
firmware, reference, deadline or protection changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import speedloop_excitation_evidence as review
import speedloop_excitation_review as excitation
from speedloop_duration_review import overrides
from speedloop_motion_gain_trial import f32

PATTERNS=((0,1,0,1,0,1,0,1,0,1,0,1),
          (1,0,1,0,1,0,1,0,1,0,1,0),
          (0,1,1,0,1,0,0,1,0,1,1,0))


def planned_gains(elapsed_ms,ki_probe_sign=0,mode='kp_probe',index=0):
    if ki_probe_sign or mode not in ('baseline','kp_probe') or index not in range(3):
        raise ValueError('Unknown bounded binary probe')
    probe=False
    if mode=='kp_probe' and 3900<=elapsed_ms<6900:
        probe=bool(PATTERNS[index][int((elapsed_ms-3900)//250)])
    return f32(.00352456 if probe else .003389),f32(.00144)


def validate(a):
    if not getattr(a,'authorized_binary_probe',False) or getattr(a,'probe_schedule_index',-1) not in range(3):
        raise ValueError('Finite binary probe scope and schedule required')
    a.authorized_excitation_evidence=True
    return review.validate(a)


def run(a):
    validate(a)
    if a.phase not in ('prepare','trial'):raise ValueError('Binary probe cannot flash')
    index=a.probe_schedule_index
    def plan(elapsed_ms,ki_probe_sign=0,mode='kp_probe'):
        return planned_gains(elapsed_ms,ki_probe_sign,mode,index)
    with overrides(excitation,planned_gains=plan):
        result=review.run(a)
    if a.phase=='trial':
        result.update(gain_mode='binary_probe',runtime_profile='250ms-binary-kp-probes-v1',
            probe_schedule_index=index,probe_schedule=list(PATTERNS[index]),
            probe_slot_ms=250,probe_source_elapsed_ms=[3900,6900],actor_applied=False,
            runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-binary-probe',action='store_true')
    p.add_argument('--probe-schedule-index',type=int,choices=range(3),required=True)
    p.add_argument('--gain-mode',choices=('kp_probe',),default='kp_probe')
    p.add_argument('--boot-token-file')
    for name in ('energized-phase-inhibited-confirmed','power-disconnected-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.phase=='trial' and not a.boot_token_file:p.error('Boot token required')
    raise SystemExit(0 if run(a)['passed'] else 1)
