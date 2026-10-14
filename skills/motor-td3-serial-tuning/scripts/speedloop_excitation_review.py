"""Exact v8 scripted-reference collection. Baseline/+4% Kp only, no Actor.

Eight seconds maximum; STOP at 7.8 seconds. A pair reserves sixteen seconds.
The v7 entry remains bound to its old image and cannot accept this image.
"""
import argparse
import hashlib
import json
from pathlib import Path
from build_speedloop_excitation_review import IDENTITY
from speedloop_duration_review import overrides
from speedloop_response_review import validate_action
import speedloop_motion_gain_trial as trial

IMAGE_SHA='697f787d3cff0f960db70a7f487aa490012732561c4cea8fc5192e0d988e4f18'
HEX_SHA='ea1f3ff8af4977ca2405fbe79ba81364f09dbf5f2ac91f7344873cb24becd881'
OLD_SHA='9c1a76f9cd8d511d8580178743e7cf2cc828956a04fea304e03805048a6d2b6d'
OLD_BYTES=50308
IMAGE_BYTES=50456
HALL_TRACE_CAPACITY=768
REFERENCE_SCHEDULE=[[0,1000],[4000,1100],[5200,900],[6400,1000]]
BASE_CHECK=trial.check_telemetry


def validate(args):
    if not getattr(args,'authorized_excitation_review',False):
        raise ValueError('Bounded scripted-reference experiment authorization required')
    build=Path(args.build).resolve()
    info=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if (info['build_id']!=IDENTITY or not info['passed'] or info['bin_sha256']!=IMAGE_SHA or
        info['binary_bytes']!=IMAGE_BYTES or info['hall_trace_capacity']!=HALL_TRACE_CAPACITY or
        hashlib.sha256((build/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA or
        hashlib.sha256((build/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA or
        info['excitation_review']['reference_schedule_ms_rpm']!=REFERENCE_SCHEDULE or
        info['excitation_review']['maximum_motion_seconds']!=8 or
        info['excitation_review']['actor_allowed'] is not False):
        raise ValueError('Only the exact reviewed v8 excitation image is accepted')
    validate_action(args)
    return info


def planned_gains(elapsed_ms,ki_probe_sign=0,mode='baseline'):
    if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported action')
    kp=.00352456 if mode=='kp_probe' and 3900<=elapsed_ms<7000 else .003389
    return trial.f32(kp),trial.f32(.00144)


def expected_reference(elapsed_ms):
    return 1000 if elapsed_ms<4000 else 1100 if elapsed_ms<5200 else 900 if elapsed_ms<6400 else 1000


def reference_matches(elapsed_ms,reference):
    if reference==expected_reference(elapsed_ms):return True
    # Snapshot and 1ms reference owner may straddle a boundary by at most 2ms.
    for (_,before),(boundary,after) in zip(REFERENCE_SCHEDULE,REFERENCE_SCHEDULE[1:]):
        if abs(elapsed_ms-boundary)<=2 and reference in (before,after):return True
    return False


def check_telemetry(obj,last,sent):
    BASE_CHECK(obj,last,sent)
    if obj['enabled'] and not reference_matches(obj['elapsed_ms'],obj['speed_ref']):
        raise RuntimeError('Actual MCU reference differs from reviewed excitation schedule')


def run(args):
    validate(args) # Before importing or attaching any hardware library.
    if args.phase=='flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
            return flash.flash(args)
    if args.phase=='prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA):return prepare.prepare(args)
    if args.phase!='trial':raise ValueError('Unknown phase')
    args.ki_probe_sign=0;args.apply_shadow_kp=False
    with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,
        STOP_SECONDS=7.8,GAIN_CUTOFF_SECONDS=7.7,FINAL_GAIN_SECONDS=7.72,
        FINAL_GAIN_DEADLINE_SECONDS=7.75,MAX_MOTION_SECONDS=8,CAPTURE_SECONDS=10,
        TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing',HALL_TRACE_CAPACITY=HALL_TRACE_CAPACITY,
        planned_gains=planned_gains,check_telemetry=check_telemetry):
        result=trial.trial(args)
    result.update(runtime_profile='two-round-8s-excitation-review-v1',
        runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reference_schedule_ms_rpm=REFERENCE_SCHEDULE,probe_source_elapsed_ms=[3900,7000],
        actor_applied=False,ordinary_deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-excitation-review',action='store_true')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in needed[a.phase]):p.error('Missing phase-specific file paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
