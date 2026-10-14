"""Exact v23, finite reference/gain excitation capture. No Actor application."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import speedloop_fullhall_probe as base
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from build_speedloop_reference_v23 import IDENTITY,reference_rpm

IMAGE_SHA='33ffa5e04d69a0505b99596f6e7bdfc8cd0754539ba1252f15e5ce7345b6bbbf'
HEX_SHA='2def40ec0a2006e23e0cf203cf5ab9ab9c035bcdb64a849c7babfbf1451f9ba0'
IMAGE_BYTES=51272
OLD_SHA=base.IMAGE_SHA
OLD_BYTES=base.IMAGE_BYTES
BASE_CONTEXT=base.context


def reference_matches(ms,ref):
    return ref in {reference_rpm(max(0,int((ms+offset)*1000))) for offset in (-2,0,2)}


@contextmanager
def context(pattern,mode='switching-local4'):
    if mode!='switching-local4':raise ValueError('Only the declared local gain switch pattern')
    with BASE_CONTEXT(pattern,mode):
        with overrides(base.previous,PLATEAU_START_MS=6250,PLATEAU_END_MS=22250,
            REFERENCE_MATCHES=reference_matches):
            yield


def validate(a):
    if not getattr(a,'authorized_reference_steps',False):raise ValueError('Finite reference excitation authorization required')
    info=json.loads((Path(a.build)/'summary.json').read_text())
    review=info.get('reference_v23_review',{})
    checks=json.loads(Path(a.adapter_checks).read_text())
    if (info.get('build_id')!=IDENTITY or info.get('bin_sha256')!=IMAGE_SHA
        or info.get('hex_sha256')!=HEX_SHA or info.get('binary_bytes')!=IMAGE_BYTES
        or not info.get('passed') or not checks.get('passed')
        or not checks.get('reference_v23_checks',{}).get('old_stop_and_guard_checks_retained')
        or not checks.get('reference_v23_checks',{}).get('exact_step_boundaries_checked')
        or review.get('reference_levels_rpm')!=[950,1000,1050]
        or review.get('active_reference_start_us')!=6000000
        or review.get('active_reference_end_us')!=22000000
        or review.get('reference_slot_us')!=2000000
        or review.get('control_period_changed') is not False
        or review.get('protection_limits_changed') is not False
        or review.get('gain_allowlist_changed') is not False
        or review.get('sensor_filter_changed') is not False
        or review.get('thermal_gate_modified') is not False
        or review.get('actor_allowed') is not False
        or hashlib.sha256((Path(a.build)/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA
        or hashlib.sha256((Path(a.build)/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA):
        raise ValueError('Only the exact reviewed reference image with retained protections')
    a.authorized_continuous=True
    if a.phase=='flash':
        with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
            continuous.validate(a)
        return info
    cfg=json.loads(Path(a.schedule_contract).read_text())
    if (cfg.get('reference_profile')!='exogenous-v23-950-1000-1050'
        or cfg.get('reference_pattern_rpm')!=[1000,950,1000,1050,1000,950,1000,1050]
        or cfg.get('reference_start_ms')!=6000 or cfg.get('reference_slot_ms')!=2000
        or cfg.get('reference_finish_ms')!=22000 or cfg.get('plateau_start_ms')!=6250
        or cfg.get('gain_switches_offset_from_reference_ms')!=250
        or cfg.get('old_fixed_reference_training_allowed') is not False
        or cfg.get('old_lower16_training_allowed') is not False):
        raise ValueError('Reference and action clocks must be explicitly separated before motion')
    a.probe_mode='switching-local4';a.authorized_fullhall_probe=True
    with overrides(base,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
        IMAGE_BYTES=IMAGE_BYTES,context=context):
        base.validate(a)
    return info


def run(a):
    validate(a)
    if a.phase=='flash':
        import can
        from can.interfaces.pcan import basic
        basic.PCANBasic()
        with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
            IMAGE_BYTES=IMAGE_BYTES,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
            return continuous.run(a)
    with overrides(base,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
        IMAGE_BYTES=IMAGE_BYTES,context=context):
        result=base.run(a)
    if a.phase=='trial':
        result.update(reference_profile='exogenous-v23-950-1000-1050',
            gain_switches_offset_from_reference_ms=250,old_fixed_reference_training_allowed=False,
            reference_steps_are_behavior_excitation=True,independent_frozen_actor_evaluation=False,
            candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output','adapter-checks'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','schedule-contract','previous-trial-summary','boot-token-file','stream-output','debug-read-benchmark'):
        p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    p.add_argument('--hall-read-profile',default='pipelined-v1',choices=('pipelined-v1',))
    p.add_argument('--debug-read-frequency-hz',default=1000000,type=int,choices=(1000000,4000000))
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for name in ('authorized-reference-steps','energized-update-authorized','energized-phase-inhibited-confirmed',
        'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),
        'prepare':('nm','schedule_contract','previous_trial_summary'),
        'trial':('nm','schedule_contract','previous_trial_summary','boot_token_file','stream_output')}
    if any(not getattr(a,name) for name in required[a.phase]):p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
