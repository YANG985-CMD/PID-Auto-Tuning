"""Exact-image, one-time 5s BASELINE review. No Actor, exploration or batch runner.

The separate --authorized-single-5s-review flag is required for every phase;
the old 3s approval and live entry points cannot silently extend their limit.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from build_speedloop_duration_review import IDENTITY

IMAGE_SHA = '9893d373bee3c4540eab0f496753595aee3a6998db29c2d1dc3ac6833976228a'
HEX_SHA = 'bfa86a499f10459a1c3750d0d85e4c08bccf0828df59771367dfc337a7a3a993'
PREVIOUS_SHA = '45ad8fcd5039822741d888cb54eaea909cfc55d3e13dc8da0cdfcfc98703cce5'


def validate(args):
    if not getattr(args,'authorized_single_5s_review',False):
        raise ValueError('A separate single five-second baseline experiment approval is required')
    build=Path(args.build).resolve()
    info=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if (info['build_id']!=IDENTITY or not info['passed'] or info['bin_sha256']!=IMAGE_SHA or
        hashlib.sha256((build/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA or
        hashlib.sha256((build/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA or
        info['duration_review']['mode']!='single fixed baseline PI; no Actor or gain exploration' or
        info['duration_review']['maximum_motion_seconds']!=5):
        raise ValueError('Only the exact reviewed five-second baseline image is accepted')
    return info


@contextmanager
def overrides(module, **values):
    old={name:getattr(module,name) for name in values}
    try:
        for name,value in values.items():setattr(module,name,value)
        yield
    finally:
        for name,value in old.items():setattr(module,name,value)


def run(args):
    validate(args) # Before importing any hardware library or attaching a probe.
    if args.phase=='flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,OLD_SHA=PREVIOUS_SHA):
            return flash.flash(args)
    if args.phase=='prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA):
            return prepare.prepare(args)
    if args.phase!='trial':raise ValueError('Unknown experiment phase')
    # Explicitly reject accidental use as a longer Actor/probe runner.
    if (getattr(args,'apply_shadow_kp',False) or getattr(args,'shadow_port',None) or
        getattr(args,'ki_probe_sign',0) or getattr(args,'gain_mode','baseline')!='baseline'):
        raise ValueError('Five-second review permits fixed baseline PI only')
    import speedloop_motion_gain_trial as trial
    args.gain_mode='baseline';args.ki_probe_sign=0;args.apply_shadow_kp=False
    with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,
        STOP_SECONDS=4.8,GAIN_CUTOFF_SECONDS=4.7,FINAL_GAIN_SECONDS=4.72,
        FINAL_GAIN_DEADLINE_SECONDS=4.75,MAX_MOTION_SECONDS=5,CAPTURE_SECONDS=7,
        TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing'):
        report=trial.trial(args)
    report['runtime_profile']='single-5s-fixed-baseline-review-v1'
    report['runtime_profile_script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['ordinary_deployment_allowed']=False
    report['performance_claim_allowed']=False
    (Path(args.output)/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--uid',default='0674FF554850715087183841')
    parser.add_argument('--authorized-single-5s-review',action='store_true')
    parser.add_argument('--nm');parser.add_argument('--boot-token-file')
    parser.add_argument('--pyocd');parser.add_argument('--pack')
    parser.add_argument('--energized-update-authorized',action='store_true')
    parser.add_argument('--power-disconnected-confirmed',action='store_true')
    parser.add_argument('--energized-phase-inhibited-confirmed',action='store_true')
    parser.add_argument('--power-confirmed',action='store_true')
    parser.add_argument('--authorized-no-thermal-trial',action='store_true')
    args=parser.parse_args()
    required={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(args,k) for k in required[args.phase]):parser.error('Missing phase-specific file paths')
    raise SystemExit(0 if run(args)['passed'] else 1)
