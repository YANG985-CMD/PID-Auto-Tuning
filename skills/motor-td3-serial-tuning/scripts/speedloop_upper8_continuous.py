"""Exact v25 finite interior probes. Continuous firmware is not Actor approval."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import time
from pathlib import Path
import speedloop_continuous as continuous
import speedloop_lower16_probe as staged
from speedloop_duration_review import overrides
from speedloop_stream_training import UPPER8_DENSE_GAINS,KI
from speedloop_motion_gain_trial import f32
from build_speedloop_upper8_continuous import IDENTITY
from speedloop_upper8_probe import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES

IMAGE_SHA='389a05e12240e37a24a58403df691adb3f20baa499756214a3c0af6f05a98cdf'
HEX_SHA='cbaf82b81df9d7f2e34480494dfdccc9ea4489702cb33aa9907fccf9383a187d'
IMAGE_BYTES=51188
LEVELS=UPPER8_DENSE_GAINS
PATTERNS=((0,2,6,8),(8,6,2,0))
HOST_STEP=f32(.00013556)
PLATEAU_START_MS=4000
PLATEAU_MS=4500
PLATEAU_END_MS=22000
ANALYSIS_SETTLE_MS=200
ANALYSIS_END_MARGIN_MS=200
VERSION='upper8-continuous-interface-interior-probe-v2'
HALL_READ_PROFILE='pipelined-chunk8-v2'

class ContinuousUpperProbe:
    def __init__(self,pattern):self.pattern=pattern;self.slot=-1;self.actual=LEVELS[0];self.decisions=[]
    def observe(self,t):
        if not t.get('enabled',True) or not t.get('applied_seq',1):return
        if t['kp'] not in LEVELS or t['ki']!=KI:raise RuntimeError('Unknown actual experimental gain')
        self.actual=t['kp']
    def planned(self,elapsed,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode!='kp_probe':raise ValueError('Fixed Ki, no Actor')
        slot=int((elapsed-PLATEAU_START_MS)//PLATEAU_MS) if PLATEAU_START_MS<=elapsed<PLATEAU_END_MS else -1
        if slot>=0 and (slot<self.slot or self.slot>=0 and slot>self.slot+1):
            raise RuntimeError('Missed declared plateau')
        if elapsed>=PLATEAU_END_MS and self.slot>=0 and self.slot!=len(self.pattern)-1:
            raise RuntimeError('Missed final declared plateau')
        if slot>=0:self.slot=slot
        target=LEVELS[self.pattern[slot]] if slot>=0 else LEVELS[0]
        reachable=[v for v in LEVELS if abs(v-self.actual)<=HOST_STEP+1e-9]
        command=min(reachable,key=lambda v:abs(v-target))
        if abs(command-self.actual)>HOST_STEP+1e-9:raise RuntimeError('Host slew exceeded')
        self.decisions.append(dict(source_elapsed_ms=elapsed,slot=slot,actual_kp=self.actual,
            target_kp=target,command_kp=command,intermediate_bridge=command!=target))
        return command,KI

def confirmed_stop_cooldown(summary_path,clock=None):
    """Use a received disabled state AFTER STOP, not the trial-entry timestamp."""
    path=Path(summary_path)
    commands=[json.loads(line) for line in path.with_name('commands.jsonl').read_text(encoding='utf-8').splitlines()]
    stops=[c['host_monotonic'] for c in commands if c['type']=='stop']
    if len(stops)!=1:raise ValueError('One verified STOP command required for cooldown')
    packets=[json.loads(line) for line in path.with_name('telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    confirmed=[p['host_received_monotonic'] for p in packets if not p['enabled'] and not p['fault']
        and p['host_received_monotonic']-stops[0]>=.1]
    if not confirmed:raise ValueError('Actual disabled-state acknowledgement missing for cooldown')
    elapsed=(time.perf_counter() if clock is None else clock)-max(confirmed)
    if elapsed<0:raise ValueError('Host monotonic clock changed; cannot reuse cooldown proof')
    return elapsed

def validate(a):
    if not getattr(a,'authorized_continuous_upper8_probe',False):raise ValueError('Bounded interior exploration scope required')
    if getattr(a,'schedule_index',0) not in (0,1):raise ValueError('Only two declared schedules')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    review=info.get('continuous_upper8_review',{})
    checks=json.loads(Path(a.adapter_checks).read_text(encoding='utf-8'))
    if (not checks.get('passed') or not checks.get('continuous_upper8_checks',{}).get('retained_stop_and_guard_checks')
        or review.get('firmware_response_kp_domain')!=[.003389,.00366012]
        or review.get('fixed_ki')!=.00144 or review.get('reference_rpm')!=1000
        or review.get('host_single_kp_step_limit')!=.00013556
        or review.get('firmware_single_kp_step_limit')!=.00027112
        or review.get('general_parameter_and_physical_limits_changed') is not False
        or review.get('control_period_changed') is not False or review.get('sensor_filter_changed') is not False
        or review.get('thermal_gate_modified') is not False or review.get('actor_allowed') is not False):
        raise ValueError('Exact v25 review and retained guards required')
    if Path(a.output).exists():raise ValueError('One-use output already exists')
    if a.phase=='flash':return info
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    expected=dict(version=VERSION,requested_rounds=1,reserved_motion_seconds=24,
        maximum_batch_rounds=2,maximum_batch_motion_seconds=48,minimum_cooldown_seconds=30,
        exact_kp_levels=list(LEVELS),fixed_ki=KI,reference_rpm=1000,
        pattern=list(PATTERNS[a.schedule_index]),plateau_start_ms=PLATEAU_START_MS,plateau_ms=PLATEAU_MS,
        analysis_settle_ms=ANALYSIS_SETTLE_MS,analysis_end_margin_ms=ANALYSIS_END_MARGIN_MS,
        actor_applied=False,fault_automatic_retry=False,training_performed=False,
        action_mapping_redefinition_required=True,live_hall_capture=True,
        hall_read_profile=HALL_READ_PROFILE,debug_read_frequency_hz=4000000,
        host_single_kp_step_limit=.00013556,firmware_single_kp_step_limit=.00027112,
        exact_image_sha256=IMAGE_SHA,thermal_gate_modified=False,
        deployment_allowed=False,performance_claim_allowed=False,fault_ends_entire_batch=True)
    if any(cfg.get(k)!=v for k,v in expected.items()):raise ValueError('Predeclared finite experiment mismatch')
    if cfg.get('whole_boot_role')!=('train' if a.schedule_index==0 else 'validation'):
        raise ValueError('Frozen whole-boot split required')
    old=json.loads(Path(a.previous_trial_summary).read_text(encoding='utf-8'))
    if not old.get('passed'):
        # Explicit fresh human authorization after this exact host timeout.
        # Never substitutes an earlier passed round or clears an electrical fault.
        recovery=json.loads(Path(a.recovery_readonly).read_text(encoding='utf-8')) if getattr(a,'recovery_readonly',None) else {}
        if (a.schedule_index!=0 or not getattr(a,'fault_recovery_authorized',False)
            or cfg.get('fresh_human_fault_recovery_authorization') is not True
            or cfg.get('previous_failed_summary_sha256')!=hashlib.sha256(Path(a.previous_trial_summary).read_bytes()).hexdigest()
            or old.get('error')!='Hall read exceeded reserved 6ms budget'
            or old.get('final_irq_fault')!=0 or old.get('final_tx_fault')!=0
            or old.get('bin_sha256')!=IMAGE_SHA
            or not old.get('core_halted_after_physical_shutdown') or not old.get('can_released_after_shutdown')
            or not recovery.get('passed') or recovery.get('full_readback_sha256')!=IMAGE_SHA
            or cfg.get('recovery_readonly_sha256')!=hashlib.sha256(Path(a.recovery_readonly).read_bytes()).hexdigest()):
            raise ValueError('Faulted prior batch requires a fresh exact stopped proof and direct human recovery authorization')
    else:staged.validate_prior_trial(a,old)
    if old.get('passed') and confirmed_stop_cooldown(a.previous_trial_summary)<30:
        raise ValueError('Less than 30 seconds since the actual STOP acknowledgement')
    if (datetime.now(timezone.utc)-datetime.fromisoformat(old['utc'])).total_seconds()-26<30:
        raise ValueError('Minimum cooldown not reached')
    if a.phase=='trial':
        qpath=Path(a.bounded_reader_benchmark);q=json.loads(qpath.read_text(encoding='utf-8'))
        if (not q.get('passed') or q.get('profile')!=HALL_READ_PROFILE or q.get('samples')!=1000
            or q.get('over_6ms')!=0 or q.get('firmware_sha256')!=IMAGE_SHA
            or any(q.get(k) is not False for k in ('hardware_written','reset','resume','motion_started'))
            or cfg.get('bounded_reader_benchmark_sha256')!=hashlib.sha256(qpath.read_bytes()).hexdigest()
            or cfg.get('Hall_reader_source_sha256')!=hashlib.sha256((Path(__file__).parent/'live_speedloop_hall.py').read_bytes()).hexdigest()):
            raise ValueError('Exact bounded-reader qualification and source required')
        bpath=Path(a.debug_read_benchmark);b=json.loads(bpath.read_text(encoding='utf-8'))
        rows=[r for r in b['rows'] if r['frequency_hz']==4000000]
        if (not b.get('passed') or b.get('firmware_sha256')!=IMAGE_SHA
            or any(b.get(k) is not False for k in ('hardware_written','reset','resume'))
            or {r['records'] for r in rows}!={4,8,12}
            or not all(r['samples']>=100 and r['over_6ms']==0 and r['content_identical'] for r in rows)
            or cfg.get('debug_read_benchmark_sha256')!=hashlib.sha256(bpath.read_bytes()).hexdigest()
            or getattr(a,'debug_read_frequency_hz',None)!=4000000):
            raise ValueError('Exact v25 read qualification required')
    return info

def run(a):
    validate(a)
    import can
    from can.interfaces.pcan import basic
    basic.PCANBasic()
    a.stream_gain_levels=LEVELS;a.capture_only=True;a.trainer_ready_file=None
    a.capture_hall_capacity=832;a.capture_hall_read_profile=HALL_READ_PROFILE
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
        OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,
        ContinuousProbe=lambda:ContinuousUpperProbe(PATTERNS[a.schedule_index]),reference_matches=lambda ms,ref:ref==1000):
        result=continuous.run(a)
    result.update(continuous_upper8_experimental_probe=True,actor_applied=False,candidate_admission=False,
        deployment_allowed=False,performance_claim_allowed=False)
    if a.phase=='trial':
        result.update(probe_pattern=list(PATTERNS[a.schedule_index]),plateau_start_ms=PLATEAU_START_MS,plateau_ms=PLATEAU_MS,
            exact_kp_levels=list(LEVELS),fixed_reference_rpm=1000,host_single_kp_step_limit=.00013556,
            capture_only=True,online_training_performed=False,live_hall_capture=True,
            hall_read_profile=HALL_READ_PROFILE,debug_read_frequency_hz=4000000,
            primary_metric_version='raw-Hall-held-time-integral-v1',action_mapping_redefinition_required=True,
            physical_behavior_probe_not_frozen_actor=True,
            schedule_contract_sha256=hashlib.sha256(Path(a.schedule_contract).read_bytes()).hexdigest())
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output','adapter-checks'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','schedule-contract','previous-trial-summary','boot-token-file','stream-output','debug-read-benchmark',
        'bounded-reader-benchmark','recovery-readonly'):
        p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    p.add_argument('--debug-read-frequency-hz',default=4000000,type=int,choices=(4000000,))
    for name in ('authorized-continuous-upper8-probe','fault-recovery-authorized','energized-update-authorized','energized-phase-inhibited-confirmed',
        'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();needed={'flash':('pyocd','pack'),
        'prepare':('nm','schedule_contract','previous_trial_summary'),
        'trial':('nm','schedule_contract','previous_trial_summary','boot_token_file','stream_output','debug_read_benchmark','bounded_reader_benchmark')}
    if any(not getattr(a,n) for n in needed[a.phase]):p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
