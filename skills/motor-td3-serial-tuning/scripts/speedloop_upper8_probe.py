"""One finite +8% probe, actual ACK through +4%, no Actor or training."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import speedloop_continuous as continuous
import speedloop_lower16_probe as staged
from speedloop_duration_review import overrides
from speedloop_stream_training import UPPER8_GAINS
from speedloop_motion_gain_trial import f32
from build_speedloop_upper8_review import IDENTITY
from speedloop_reference_v23 import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES

IMAGE_SHA='42d39dcc54bae0f088a1ec0653ffdb7e9c04bae82342a4f7dd85191666d71f4f'
HEX_SHA='bcf19ff3441d2c2054b6945108a4a536a2b938cf0e1218b280930e48e73e8dc1'
IMAGE_BYTES=51200
LEVELS=UPPER8_GAINS
PATTERN=(0,2,2,0,0,2,2,0)
PATTERNS=(PATTERN,tuple(2-level for level in PATTERN))
HOST_STEP=f32(.00013556)
PLATEAU_START_MS=6000
PLATEAU_MS=2000
ANALYSIS_SETTLE_MS=200
ANALYSIS_END_MARGIN_MS=200

def validate(a):
    if not getattr(a,'authorized_upper8_probe',False):raise ValueError('Explicit finite expanded exploration scope required')
    index=getattr(a,'schedule_index',0)
    if index not in (0,1):raise ValueError('Only the two complementary predeclared schedules')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    review=info.get('upper8_review',{})
    checks=json.loads(Path(a.adapter_checks).read_text(encoding='utf-8'))
    if (not checks.get('passed') or not checks.get('upper8_checks',{}).get('retained_stop_and_guard_checks')
        or review.get('exact_kp_levels')!=[.003389,.00352456,.00366012]
        or review.get('fixed_ki')!=.00144 or review.get('reference_rpm')!=1000
        or review.get('required_bridge_kp')!=.00352456
        or review.get('host_single_kp_step_limit')!=.00013556
        or review.get('firmware_single_kp_step_limit')!=.00027112
        or review.get('general_parameter_and_physical_limits_changed') is not False
        or review.get('control_period_changed') is not False
        or review.get('sensor_filter_changed') is not False
        or review.get('thermal_gate_modified') is not False
        or review.get('actor_allowed') is not False):
        raise ValueError('Exact upper8 image and retained guard checks required')
    if Path(a.output).exists():raise ValueError('One-use phase output already exists')
    if a.phase=='flash':return info
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    expected=dict(requested_rounds=1,reserved_motion_seconds=24,maximum_batch_rounds=1,
        maximum_batch_motion_seconds=24,minimum_cooldown_seconds=30,
        exact_kp_levels=list(LEVELS),fixed_ki=staged.KI,reference_rpm=1000,
        pattern=list(PATTERNS[index]),plateau_start_ms=PLATEAU_START_MS,plateau_ms=PLATEAU_MS,
        analysis_settle_ms=ANALYSIS_SETTLE_MS,analysis_end_margin_ms=ANALYSIS_END_MARGIN_MS,
        actor_applied=False,fault_automatic_retry=False,training_performed=False,
        action_mapping_redefinition_required=True,old_lower16_training_allowed=False,
        live_hall_capture=True,gain_exploration=True,hall_read_profile='pipelined-v1',
        debug_read_frequency_hz=4000000,host_single_kp_step_limit=.00013556,
        firmware_single_kp_step_limit=.00027112,exact_image_sha256=IMAGE_SHA,
        deployment_allowed=False,performance_claim_allowed=False)
    if any(cfg.get(k)!=v for k,v in expected.items()):raise ValueError('Predeclared one-round experiment contract mismatch')
    old=json.loads(Path(a.previous_trial_summary).read_text(encoding='utf-8'))
    staged.validate_prior_trial(a,old)
    if (datetime.now(timezone.utc)-datetime.fromisoformat(old['utc'])).total_seconds()-26<30:
        raise ValueError('Minimum cooldown not reached')
    if a.phase=='trial':
        bpath=Path(a.debug_read_benchmark);b=json.loads(bpath.read_text(encoding='utf-8'))
        rows=[r for r in b['rows'] if r['frequency_hz']==4000000]
        if (not b.get('passed') or b.get('firmware_sha256')!=IMAGE_SHA
            or b.get('hardware_written') is not False or b.get('reset') is not False or b.get('resume') is not False
            or {r['records'] for r in rows}!={4,8,12}
            or not all(r['samples']>=100 and r['over_6ms']==0 and r['content_identical'] for r in rows)
            or cfg.get('debug_read_benchmark_sha256')!=hashlib.sha256(bpath.read_bytes()).hexdigest()
            or getattr(a,'debug_read_frequency_hz',None)!=4000000):
            raise ValueError('Exact-image 4MHz read qualification required')
    return info

def run(a):
    validate(a)
    import can
    from can.interfaces.pcan import basic
    basic.PCANBasic() # Load DLL before reset or motion.
    a.stream_gain_levels=LEVELS;a.capture_only=True;a.trainer_ready_file=None
    a.capture_hall_capacity=832;a.capture_hall_read_profile='pipelined-v1'
    pattern=PATTERNS[getattr(a,'schedule_index',0)]
    with overrides(staged,LEVELS=LEVELS,PATTERN=pattern,LOWER16_GAINS=LEVELS,STEP=HOST_STEP,
        PLATEAU_START_MS=PLATEAU_START_MS,PLATEAU_MS=PLATEAU_MS,
        PLATEAU_END_MS=PLATEAU_START_MS+len(pattern)*PLATEAU_MS):
        with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
            OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,ContinuousProbe=staged.StagedProbe,
            reference_matches=lambda ms,ref:ref==1000):
            result=continuous.run(a)
    result.update(upper8_experimental_probe=True,actor_applied=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    if a.phase=='trial':
        result.update(probe_pattern=list(pattern),plateau_start_ms=PLATEAU_START_MS,plateau_ms=PLATEAU_MS,
            exact_kp_levels=list(LEVELS),fixed_reference_rpm=1000,
            host_single_kp_step_limit=.00013556,firmware_single_kp_step_limit=.00027112,
            capture_only=True,online_training_performed=False,live_hall_capture=True,
            gain_exploration=True,hall_read_profile='pipelined-v1',debug_read_frequency_hz=4000000,
            primary_metric_version='raw-Hall-held-time-integral-v1',
            action_mapping_redefinition_required=True,
            schedule_contract_sha256=hashlib.sha256(Path(a.schedule_contract).read_bytes()).hexdigest())
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output','adapter-checks'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','schedule-contract','previous-trial-summary','boot-token-file','stream-output','debug-read-benchmark'):
        p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    p.add_argument('--debug-read-frequency-hz',default=4000000,type=int,choices=(4000000,))
    for name in ('authorized-upper8-probe','energized-update-authorized','energized-phase-inhibited-confirmed',
        'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),
        'prepare':('nm','schedule_contract','previous_trial_summary'),
        'trial':('nm','schedule_contract','previous_trial_summary','boot_token_file','stream_output','debug_read_benchmark')}
    if any(not getattr(a,n) for n in required[a.phase]):p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
