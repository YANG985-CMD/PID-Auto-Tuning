"""Exact-image eight-second response review. No Actor or Ki changes.

Batch reservation is at most two rounds / sixteen seconds. Faults stop the
batch; there is no automatic retry. This does not open ordinary deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path
from build_speedloop_response_review import IDENTITY
from speedloop_duration_review import overrides
import speedloop_motion_gain_trial as trial

IMAGE_SHA = '9c1a76f9cd8d511d8580178743e7cf2cc828956a04fea304e03805048a6d2b6d'
HEX_SHA = '508f441d5fa280a14ffbc2b2d3bc001d41ab90d846f877a5cfd3032ac0541158'
OLD_SHA = '9893d373bee3c4540eab0f496753595aee3a6998db29c2d1dc3ac6833976228a'
OLD_BYTES = 50108


def validate(args):
    if not getattr(args,'authorized_response_review',False):
        raise ValueError('Bounded eight-second response experiment authorization required')
    build=Path(args.build).resolve()
    info=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if (info['build_id']!=IDENTITY or not info['passed'] or info['bin_sha256']!=IMAGE_SHA or
        hashlib.sha256((build/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA or
        hashlib.sha256((build/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA or
        info['response_review']['maximum_motion_seconds']!=8 or info['hall_trace_capacity']!=768):
        raise ValueError('Only the exact reviewed eight-second response image is accepted')
    validate_action(args)
    return info


def validate_action(args):
    if (getattr(args,'gain_mode','baseline') not in ('baseline','kp_probe') or
        getattr(args,'ki_probe_sign',0) or getattr(args,'apply_shadow_kp',False) or
        getattr(args,'shadow_port',None)):
        raise ValueError('Response review permits baseline and prescribed +4% Kp pulse only')


def planned_gains(elapsed_ms, ki_probe_sign=0, mode='baseline'):
    if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported action')
    kp=.00352456 if mode=='kp_probe' and 5000<=elapsed_ms<6000 else .003389
    return trial.f32(kp),trial.f32(.00144)


def run(args):
    validate(args) # Must reject before importing/attaching any hardware library.
    if args.phase=='flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,
                       OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
            return flash.flash(args)
    if args.phase=='prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA):
            return prepare.prepare(args)
    if args.phase!='trial':raise ValueError('Unknown phase')
    args.ki_probe_sign=0;args.apply_shadow_kp=False
    with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,
        STOP_SECONDS=7.8,GAIN_CUTOFF_SECONDS=7.7,FINAL_GAIN_SECONDS=7.72,
        FINAL_GAIN_DEADLINE_SECONDS=7.75,MAX_MOTION_SECONDS=8,CAPTURE_SECONDS=10,
        TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing',HALL_TRACE_CAPACITY=768,
        planned_gains=planned_gains):
        result=trial.trial(args)
    result.update(runtime_profile='two-round-8s-response-review-v1',
        runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        probe_source_elapsed_ms=[5000,6000],actor_applied=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-response-review',action='store_true')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in needed[a.phase]):p.error('Missing phase-specific file paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
