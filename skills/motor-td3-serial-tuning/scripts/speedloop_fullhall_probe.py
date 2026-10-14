"""Finite v22 fixed-Ki probe with predeclared complete-Hall scoring.

Reuses the exact validated image; no Flash operation or Actor writeback.
Complementary schedules are separate boot sessions, not automatic retries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import speedloop_lower16_probe as previous
from speedloop_duration_review import overrides
from speedloop_sampling_v22 import IDENTITY, IMAGE_SHA, HEX_SHA, IMAGE_BYTES
from speedloop_stream_training import LOWER_GAINS

PATTERNS = ((0, 2, 2, 0, 0, 2, 2, 0), (2, 0, 0, 2, 2, 0, 0, 2))
MIDDLE_PATTERNS = ((0, 1, 1, 0, 0, 1, 1, 0), (1, 0, 0, 1, 1, 0, 0, 1))
UPPER4_LEVELS = tuple(map(previous.f32, (.003389, .00345678, .00352456)))
SWITCH_LEVELS = tuple(map(previous.f32, (.003389, .00325344, .00352456)))
SWITCH_PATTERNS = ((0,1,0,2)*8,(0,2,0,1)*8)
METRIC = 'raw-Hall-held-time-integral-v1'
BASE_PRIOR_VALIDATOR=previous.validate_prior_trial


def declared_pattern(a,cfg):
    mode=getattr(a,'probe_mode','endpoints')
    if mode not in ('endpoints','middle','upper4','switching-local4') or cfg.get('probe_mode','endpoints')!=mode:
        raise ValueError('Only a predeclared exact-gain schedule is allowed')
    if mode in ('upper4','switching-local4') and (cfg.get('action_mapping_redefinition_required') is not True
        or cfg.get('old_lower16_training_allowed') is not False):
        raise ValueError('Positive Kp probes cannot enter the negative-only training mapping')
    if mode=='switching-local4':
        if (cfg.get('training_purpose')!='actual-source-gain-switch-response'
            or cfg.get('independent_performance_evaluation') is not False
            or cfg.get('actual_switch_interval_ms')!=500):
            raise ValueError('Measured switching experiment must be declared separately from performance evaluation')
        return SWITCH_PATTERNS[a.schedule_index]
    return (MIDDLE_PATTERNS if mode=='middle' else PATTERNS)[a.schedule_index]


def validate_prior_trial(a,old):
    if old.get('passed'):
        return BASE_PRIOR_VALIDATOR(a,old)
    if not getattr(a,'authorized_host_diagnostic_recovery',False):
        return BASE_PRIOR_VALIDATOR(a,old)
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    recovery=cfg.get('prior_host_diagnostic_recovery',{})
    readonly_path=Path(a.recovery_readonly)
    proof=json.loads(readonly_path.read_text(encoding='utf-8'))
    if (a.schedule_index not in (0,1) or getattr(a,'hall_read_profile','immediate-v1')!='pipelined-v1'
        or old.get('error')!='Hall read exceeded reserved 6ms budget'
        or old.get('final_irq_fault')!=0 or old.get('final_tx_fault')!=0
        or not old.get('core_halted_after_physical_shutdown') or not old.get('can_released_after_shutdown')
        or recovery.get('human_confirmed_after_diagnostic_stop') is not True
        or recovery.get('previous_summary_sha256')!=hashlib.sha256(Path(a.previous_trial_summary).read_bytes()).hexdigest()
        or recovery.get('readonly_sha256')!=hashlib.sha256(readonly_path.read_bytes()).hexdigest()
        or not proof.get('passed') or proof.get('hardware_written') is not False
        or proof.get('reset') is not False or proof.get('resume') is not False
        or proof.get('full_readback_sha256')!=IMAGE_SHA or not proof.get('core_halted')
        or proof.get('irq_fault')!=0 or proof.get('tx_fault')!=0 or proof.get('Motor_state')!=0):
        raise ValueError('A new batch needs direct post-stop confirmation and exact output-inhibited evidence')
    # Preserve the failed outcome. This exception only admits a newly authorized
    # batch after a host diagnostic timeout; it never clears a board fault.


def context(pattern,mode='endpoints'):
    extra=dict(LEVELS=UPPER4_LEVELS,LOWER16_GAINS=UPPER4_LEVELS) if mode=='upper4' else {}
    if mode=='switching-local4':
        extra=dict(LEVELS=SWITCH_LEVELS,LOWER16_GAINS=LOWER_GAINS,
            PLATEAU_MS=500,ANALYSIS_SETTLE_MS=100,ANALYSIS_END_MARGIN_MS=50)
    return overrides(previous, IDENTITY=IDENTITY, IMAGE_SHA=IMAGE_SHA,
                     HEX_SHA=HEX_SHA, IMAGE_BYTES=IMAGE_BYTES, PATTERN=pattern,
                     validate_prior_trial=validate_prior_trial,**extra)


def validate(a):
    if a.phase not in ('prepare', 'trial'):
        raise ValueError('Existing exact v22 image only; no Flash entry')
    if not getattr(a, 'authorized_fullhall_probe', False):
        raise ValueError('Finite physical probe authorization required')
    if a.schedule_index not in (0, 1):
        raise ValueError('Only the two predeclared schedules are allowed')
    cfg = json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    pattern=declared_pattern(a,cfg)
    frequency=getattr(a,'debug_read_frequency_hz',1000000)
    if frequency not in (1000000,4000000) or cfg.get('debug_read_frequency_hz',1000000)!=frequency:
        raise ValueError('SWD read clock must be predeclared and qualified')
    if frequency==4000000:
        benchmark_path=Path(a.debug_read_benchmark)
        benchmark=json.loads(benchmark_path.read_text(encoding='utf-8'))
        if (not benchmark.get('passed') or benchmark.get('hardware_written') is not False
            or benchmark.get('reset') is not False or benchmark.get('resume') is not False
            or benchmark.get('firmware_sha256')!=IMAGE_SHA
            or cfg.get('debug_read_benchmark_sha256')!=hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
            or not all(r['over_6ms']==0 and r['content_identical'] and r['samples']>=100
                for r in benchmark['rows'] if r['frequency_hz']==4000000)
            or {r['records'] for r in benchmark['rows'] if r['frequency_hz']==4000000}!={4,8,12}):
            raise ValueError('Unqualified exact-image 4MHz read clock')
    profile=getattr(a,'hall_read_profile','immediate-v1')
    if profile not in ('immediate-v1','pipelined-v1') or cfg.get('hall_read_profile','immediate-v1')!=profile:
        raise ValueError('Hall read profile must be declared before the physical trial')
    if (cfg.get('live_hall_capture') is not True
            or cfg.get('gain_exploration') is not True
            or cfg.get('primary_metric_version') != METRIC
            or cfg.get('schedule_index') != a.schedule_index
            or cfg.get('maximum_batch_rounds') not in (1,2)
            or cfg.get('maximum_batch_motion_seconds') != 24*cfg.get('maximum_batch_rounds',0)
            or cfg.get('minimum_cooldown_seconds') != 30
            or cfg.get('deployment_allowed') is not False
            or cfg.get('performance_claim_allowed') is not False):
        raise ValueError('Complete-Hall metric and finite batch must be declared')
    a.authorized_larger_exploration = True
    with context(pattern,getattr(a,'probe_mode','endpoints')):
        info = previous.validate(a)
    if (info['sampling_review']['interval_rule'] != 'stateless-u32-mix-v1'
            or info['sampling_v22_review']['control_period_changed'] is not False
            or info['sampling_v22_review']['sensor_filter_changed'] is not False
            or info['sampling_v22_review']['protection_limits_changed'] is not False):
        raise ValueError('Controller and protection settings must remain unchanged')
    return info


def run(a):
    validate(a)
    # Imports happen before reset, token consumption, CAN or motion commands.
    import can
    from can.interfaces.pcan import basic
    basic.PCANBasic()  # Load the installed driver DLL without opening a channel.
    dependencies=dict(python_can_version=can.__version__,python_can_file=can.__file__,
        source_sha256=hashlib.sha256(Path(can.__file__).read_bytes()).hexdigest(),
        PCAN_driver_loaded_before_hardware=True)
    a.capture_hall_capacity = 832
    a.capture_hall_read_profile=getattr(a,'hall_read_profile','immediate-v1')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    with context(declared_pattern(a,cfg),getattr(a,'probe_mode','endpoints')):
        result = previous.run(a)
    result['dependency_preflight']=dependencies
    if a.phase == 'trial':
        result.update(live_hall_capture=True, gain_exploration=True,
                      primary_metric_version=METRIC,
                      schedule_index=a.schedule_index,
                      probe_mode=getattr(a,'probe_mode','endpoints'),
                      hall_read_profile=a.capture_hall_read_profile,
                      debug_read_frequency_hz=getattr(a,'debug_read_frequency_hz',1000000),
                      training_performed=False,
                      actor_applied=False,
                      deployment_allowed=False,
                      performance_claim_allowed=False)
        (Path(a.output) / 'summary.json').write_text(
            json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('prepare', 'trial'))
    for name in ('build', 'output', 'nm', 'schedule-contract', 'previous-trial-summary'):
        p.add_argument('--' + name, required=True)
    for name in ('boot-token-file', 'stream-output','recovery-readonly','debug-read-benchmark'):
        p.add_argument('--' + name)
    p.add_argument('--uid', default='0674FF554850715087183841')
    p.add_argument('--schedule-index', required=True, type=int, choices=(0, 1))
    p.add_argument('--probe-mode',default='endpoints',choices=('endpoints','middle','upper4','switching-local4'))
    p.add_argument('--hall-read-profile',default='immediate-v1',choices=('immediate-v1','pipelined-v1'))
    p.add_argument('--debug-read-frequency-hz',default=1000000,type=int,choices=(1000000,4000000))
    p.add_argument('--gain-mode', default='kp_probe', choices=('kp_probe',))
    for name in ('authorized-fullhall-probe', 'energized-update-authorized',
                 'power-disconnected-confirmed', 'energized-phase-inhibited-confirmed',
                 'power-confirmed', 'authorized-no-thermal-trial','authorized-host-diagnostic-recovery'):
        p.add_argument('--' + name, action='store_true')
    a = p.parse_args()
    if a.phase == 'trial' and (not a.boot_token_file or not a.stream_output):
        p.error('One-use boot token and capture journal required')
    raise SystemExit(0 if run(a)['passed'] else 1)
