"""Exact v28 bounded lower31 capture; predetermined gain/reference clocks, no Actor."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import speedloop_continuous as continuous
import speedloop_upper8_continuous as old
from speedloop_duration_review import overrides
from build_speedloop_lower31_v28 import IDENTITY
from build_speedloop_upper8_reference_v26 import reference_rpm
from speedloop_motion_gain_trial import f32
from speedloop_bidirectional_v27 import IMAGE_SHA as PRIOR_SHA,IMAGE_BYTES as PRIOR_BYTES

IMAGE_SHA='35f22db78fbba9e3372e44705ffbe4b9a5f719f1d3bfe7b4a6b31e499bcc4c11'
HEX_SHA='1c8e98869d7319acf0ee335f6285cd170040d12b38a9e0d6f3d18aacf40c7dc1'
IMAGE_BYTES=51232
LEVELS=tuple(map(f32,(.002328243,.002460414,.002592585,.002724756,.002856927,.002989098,.003121269,.00325344)))+tuple(f32(.003389*(1+i/100)) for i in range(9))
BASE_INDEX=8;KI=old.KI
VERSION='lower31-staged-probe-baseline-v28-v1'
REFERENCE_PROFILE='exogenous-v28-lower31-950-1000-1050'
PATTERNS=(tuple(range(8,0,-1))+tuple([0]*16)+tuple(range(1,9)),tuple([8]*32))
PLATEAU_START_MS=6250;PLATEAU_END_MS=22250;PLATEAU_MS=500
HALL_READ_PROFILE='pipelined-chunk8-v2'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))

def reference_matches(ms,reference):
    return reference in {reference_rpm(max(0,int((ms+offset)*1000))) for offset in (-2,0,2)}

class ReferenceProbe:
    def __init__(self,pattern):self.pattern=pattern;self.slot=-1;self.actual=LEVELS[BASE_INDEX];self.decisions=[]
    def observe(self,t):
        if not t.get('enabled',True) or not t.get('applied_seq',1):return
        if t['kp'] not in LEVELS or t['ki']!=KI:raise RuntimeError('Unknown actual experimental gain')
        self.actual=t['kp']
    def planned(self,elapsed,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode!='kp_probe':raise ValueError('Fixed Ki, no Actor')
        if self.slot<0 and elapsed>=PLATEAU_START_MS+PLATEAU_MS:raise RuntimeError('Missed first declared gain slot')
        slot=int((elapsed-PLATEAU_START_MS)//PLATEAU_MS) if PLATEAU_START_MS<=elapsed<PLATEAU_END_MS else -1
        if slot>=0 and (slot<self.slot or self.slot>=0 and slot>self.slot+1):raise RuntimeError('Missed declared plateau')
        if elapsed>=PLATEAU_END_MS and self.slot>=0 and self.slot!=len(self.pattern)-1:raise RuntimeError('Missed final declared plateau')
        if slot>=0:self.slot=slot
        target=LEVELS[self.pattern[slot]] if slot>=0 else LEVELS[BASE_INDEX]
        reachable=[v for v in LEVELS if abs(v-self.actual)<=.00013556+1e-9]
        command=min(reachable,key=lambda v:abs(v-target))
        self.decisions.append(dict(source_elapsed_ms=elapsed,slot=slot,actual_kp=self.actual,target_kp=target,command_kp=command,intermediate_bridge=command!=target))
        return command,KI

def expected_schedule(index):
    if index not in (0,1):raise ValueError('Only two predeclared round roles')
    return dict(version=VERSION,requested_rounds=1,reserved_motion_seconds=24,
        maximum_batch_rounds=2,maximum_batch_motion_seconds=48,minimum_cooldown_seconds=30,
        exact_kp_levels=list(LEVELS),fixed_ki=KI,initial_reference_rpm=1000,
        reference_profile=REFERENCE_PROFILE,reference_levels_rpm=[950,1000,1050],
        reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
        reference_start_ms=6000,reference_slot_ms=2000,reference_finish_ms=22000,
        pattern=list(PATTERNS[index]),plateau_start_ms=PLATEAU_START_MS,plateau_end_ms=PLATEAU_END_MS,
        planned_reference_target_categories=[list(p) for p in sorted({(reference_rpm((PLATEAU_START_MS+PLATEAU_MS*k+200)*1000),level) for k,level in enumerate(PATTERNS[index])})],
        plateau_ms=PLATEAU_MS,gain_reference_clock_offset_ms=250,analysis_settle_ms=100,analysis_end_margin_ms=50,
        whole_boot_role='train' if index==0 else 'validation',actor_applied=False,
        fault_automatic_retry=False,fault_ends_entire_batch=True,training_performed=False,
        independent_performance_evaluation=False,action_mapping_redefinition_required=True,
        live_hall_capture=True,hall_read_profile=HALL_READ_PROFILE,debug_read_frequency_hz=4000000,
        host_single_kp_step_limit=.00013556,firmware_single_kp_step_limit=.00027112,
        exact_image_sha256=IMAGE_SHA,thermal_gate_modified=False,
        deployment_allowed=False,performance_claim_allowed=False)

def qualification_schedule():
    return dict(version=VERSION+'-qualification',requested_rounds=1,reserved_motion_seconds=3,
        maximum_batch_rounds=1,maximum_batch_motion_seconds=3,minimum_cooldown_seconds=30,
        qualification_only=True,fixed_kp=LEVELS[BASE_INDEX],fixed_ki=KI,reference_rpm=1000,
        host_stop_seconds=2.8,last_gain_deadline_seconds=2.75,
        firmware_independent_trial_cap_seconds=24,phase_purpose='Exact v28 startup and safely stopped Hall tail',
        live_hall_capture=False,actor_applied=False,fault_automatic_retry=False,fault_ends_entire_batch=True,
        training_performed=False,new_training_data_admission=False,
        thermal_gate_modified=False,exact_image_sha256=IMAGE_SHA,
        deployment_allowed=False,performance_claim_allowed=False)

def validate(a):
    if a.phase not in ('flash','prepare','trial','qualify'):raise ValueError('Unknown v28 phase')
    if not getattr(a,'authorized_lower31_capture',False):raise ValueError('Finite bidirectional capture scope required')
    if getattr(a,'gain_mode',None)!='kp_probe':raise ValueError('Only prescribed Kp capture')
    if a.schedule_index not in (0,1):raise ValueError('Only two frozen boot roles')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    checks=read(a.adapter_checks);review=info.get('lower31_v28_review',{})
    required=dict(response_Kp_domain=[.002328243,.00366012],fixed_Ki=.00144,
        host_single_Kp_step_limit=.00013556,firmware_single_Kp_step_limit=.00027112,gain_time_gate_us=[3800000,23100000],
        reference_levels_rpm=[950,1000,1050],active_reference_start_us=6000000,active_reference_end_us=22000000,
        reference_slot_us=2000000,reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,maximum_batch_rounds=2,maximum_batch_motion_seconds=48,
        minimum_cooldown_seconds=30,FOC_PI_ADC_Hall_timing_reference_and_guard_limits_unchanged=True,
        control_period_changed=False,sensor_filter_changed=False,thermal_gate_modified=False,actor_allowed=False,deployment_allowed=False)
    if any(review.get(k)!=v for k,v in required.items()):raise ValueError('Exact lower31 v28 review required')
    c=checks.get('lower31_v28_checks',{})
    if (not checks.get('passed') or not c.get('passed') or not c.get('retained_v27_checks')
        or not c.get('host_4percent_step_and_bumpless_readback_checked')
        or c.get('adapter_source_sha256')!=sha(Path(a.build)/'private-copy/codex-pi/motor_td3_g431_adapter.c')):
        raise ValueError('Exact v28 adapter and retained guards required')
    if Path(a.output).exists():raise ValueError('Consumed phase output cannot be reused')
    if a.phase=='flash':return info
    cfg=read(a.schedule_contract)
    expected=qualification_schedule() if a.phase=='qualify' or cfg.get('qualification_only') is True else expected_schedule(a.schedule_index)
    if a.phase=='trial' and cfg.get('qualification_only') is True:raise ValueError('Qualification cannot authorize dynamic capture')
    if any(cfg.get(k)!=v for k,v in expected.items()):raise ValueError('Predeclared v28 schedule mismatch')
    if a.phase=='qualify' and not getattr(a,'authorized_three_second_qualification',False):
        raise ValueError('Single three-second qualification scope required')
    prior=read(a.previous_trial_summary);old.staged.validate_prior_trial(a,prior)
    if (prior.get('firmware_id'),prior.get('bin_sha256')) not in (("g431-speedloop-pi-bidirectional-ref-24s-v27",PRIOR_SHA),(IDENTITY,IMAGE_SHA)):
        raise ValueError('Previous trial identity not in this reviewed transition')
    if old.confirmed_stop_cooldown(a.previous_trial_summary)<30:raise ValueError('STOP cooldown below 30 seconds')
    if (datetime.now(timezone.utc)-datetime.fromisoformat(prior['utc'])).total_seconds()-26<30:
        raise ValueError('UTC cooldown below 30 seconds')
    if a.phase=='trial':
        qpath=Path(a.bounded_reader_benchmark);q=read(qpath)
        if (not q.get('passed') or q.get('profile')!=HALL_READ_PROFILE or q.get('samples')!=1000
            or q.get('over_6ms')!=0 or q.get('firmware_sha256')!=IMAGE_SHA
            or any(q.get(k) is not False for k in ('hardware_written','reset','resume','motion_started'))
            or cfg.get('bounded_reader_benchmark_sha256')!=sha(qpath)
            or cfg.get('Hall_reader_source_sha256')!=sha(Path(__file__).parent/'live_speedloop_hall.py')):
            raise ValueError('Exact v28 bounded reader qualification required')
        path=Path(a.debug_read_benchmark);b=read(path);rows=[r for r in b['rows'] if r['frequency_hz']==4000000]
        if (not b.get('passed') or b.get('firmware_sha256')!=IMAGE_SHA
            or any(b.get(k) is not False for k in ('hardware_written','reset','resume'))
            or {r['records'] for r in rows}!={4,8,12}
            or not all(r['samples']>=100 and r['over_6ms']==0 and r['content_identical'] for r in rows)
            or cfg.get('debug_read_benchmark_sha256')!=sha(path)
            or a.debug_read_frequency_hz!=4000000):raise ValueError('Exact v28 debug qualification required')
    return info

def run(a):
    validate(a)
    import can
    from can.interfaces.pcan import basic
    basic.PCANBasic()
    if a.phase=='qualify':
        # The first stopped v28 Hall tail enables the exact-image reader test.
        # No live ring reads and no reference changes occur during this run.
        import speedloop_motion_gain_trial as trial
        with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,
            STOP_SECONDS=2.8,GAIN_CUTOFF_SECONDS=2.7,FINAL_GAIN_SECONDS=2.72,
            FINAL_GAIN_DEADLINE_SECONDS=2.75,MAX_MOTION_SECONDS=3,CAPTURE_SECONDS=5,
            TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing',HALL_TRACE_CAPACITY=832,
            planned_gains=lambda ms,sign=0,mode='kp_probe':(LEVELS[BASE_INDEX],KI)):
            result=trial.trial(a)
        result.update(qualification_only=True,live_hall_capture=False,reference_changes_executed=False,
            fixed_kp=LEVELS[BASE_INDEX],fixed_ki=KI,new_training_data_admission=False,
            firmware_independent_trial_cap_seconds=24,qualification_host_budget_seconds=3,
            last_gain_deadline_seconds=2.75,actor_applied=False,
            candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        return result
    a.stream_gain_levels=LEVELS;a.capture_only=True;a.trainer_ready_file=None
    a.capture_hall_capacity=832;a.capture_hall_read_profile=HALL_READ_PROFILE
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
        OLD_SHA=PRIOR_SHA,OLD_BYTES=PRIOR_BYTES,
        ContinuousProbe=lambda:ReferenceProbe(PATTERNS[a.schedule_index]),reference_matches=reference_matches):
        result=continuous.run(a)
    result.update(reference_profile=REFERENCE_PROFILE,initial_reference_rpm=1000,
        actual_reference_levels_rpm=[950,1000,1050],gain_reference_clock_offset_ms=250,
        capture_only=True,old_fixed_reference_training_allowed=False,
        new_reference_reward_contract_required=True,actor_applied=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    if a.phase=='trial':
        result.update(probe_pattern=list(PATTERNS[a.schedule_index]),plateau_start_ms=PLATEAU_START_MS,
            plateau_ms=PLATEAU_MS,hall_read_profile=HALL_READ_PROFILE,debug_read_frequency_hz=4000000,
            live_hall_capture=True,exact_kp_levels=list(LEVELS),fixed_ki=KI,
            schedule_contract_sha256=sha(a.schedule_contract),primary_metric_version='raw-Hall-held-time-integral-v1')
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial','qualify'))
    for name in ('build','output','adapter-checks'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','schedule-contract','previous-trial-summary','boot-token-file','stream-output',
                 'debug-read-benchmark','bounded-reader-benchmark'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--schedule-index',type=int,choices=(0,1),default=0)
    p.add_argument('--gain-mode',choices=('kp_probe',),default='kp_probe');p.add_argument('--debug-read-frequency-hz',type=int,default=4000000)
    for name in ('authorized-lower31-capture','energized-update-authorized','energized-phase-inhibited-confirmed',
                 'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial',
                 'authorized-three-second-qualification'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
