"""One 24s baseline-only observation qualification, complete Hall capture."""
import argparse
import json
from pathlib import Path
import speedloop_lower16_probe as previous
from speedloop_duration_review import overrides
from speedloop_lower16_probe import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES
from build_speedloop_sampling_v22 import IDENTITY

IMAGE_SHA='7d504d903ddf8c1808471e722880dc93b429ea88708c43e2a100fb23537e1f1a'
HEX_SHA='563d6b7be9675279a74a3eba757fb56de5a566a6fd15c6b52998563ad0dcbd84'
IMAGE_BYTES=51188
PATTERN=(0,)*8

def validate(a):
    if not getattr(a,'authorized_sampling_qualification',False):raise ValueError('Finite observation trial scope required')
    info=json.loads((Path(a.build)/'summary.json').read_text(encoding='utf-8'))
    r=info.get('sampling_v22_review',{})
    if (r.get('fixed_kp')!=.003389 or r.get('fixed_ki')!=.00144 or r.get('reference_rpm')!=1000
        or r.get('control_period_changed') is not False or r.get('sensor_filter_changed') is not False
        or r.get('protection_limits_changed') is not False or r.get('thermal_gate_modified') is not False
        or r.get('actor_allowed') is not False or info['sampling_review']['interval_rule']!='stateless-u32-mix-v1'):
        raise ValueError('Only observation changed; controller/limits must match')
    if a.phase!='flash':
        cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
        if (cfg.get('live_hall_capture') is not True or cfg.get('gain_exploration') is not False
            or cfg.get('primary_metric_version')!='raw-Hall-held-time-integral-v1'):
            raise ValueError('Full Hall metric must be declared before capture')
    a.authorized_larger_exploration=True
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
        IMAGE_BYTES=IMAGE_BYTES,PATTERN=PATTERN,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
        return previous.validate(a)

def run(a):
    validate(a);a.capture_hall_capacity=832
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
        IMAGE_BYTES=IMAGE_BYTES,PATTERN=PATTERN,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
        result=previous.run(a)
    if a.phase=='trial':
        result.update(observation_qualification=True,gain_exploration=False,
            fixed_kp=.003389,live_hall_capture=True,primary_metric_version='raw-Hall-held-time-integral-v1',
            sensor_filter_changed=False,control_period_changed=False,training_performed=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for n in ('build','output'):p.add_argument('--'+n,required=True)
    for n in ('nm','pyocd','pack','boot-token-file','stream-output','schedule-contract','previous-trial-summary'):p.add_argument('--'+n)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for n in ('authorized-sampling-qualification','energized-update-authorized','power-disconnected-confirmed',
        'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+n,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),'prepare':('nm','schedule_contract','previous_trial_summary'),
        'trial':('nm','schedule_contract','previous_trial_summary','boot_token_file','stream_output')}
    if any(not getattr(a,n) for n in required[a.phase]):p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
