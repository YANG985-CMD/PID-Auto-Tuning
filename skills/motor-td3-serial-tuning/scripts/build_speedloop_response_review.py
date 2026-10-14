"""Offline eight-second baseline/local-Kp response experiment; never opens hardware.

The v6 baseline-only image and its live entry remain unchanged. This separate
identity allows only the previously measured +4% Kp pulse late in RunStage.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_pi_integration as original
import build_speedloop_duration_review as previous
from build_g431_locked_foc import replace_once

IDENTITY = 'g431-speedloop-pi-response-8s-v7'


def patch_port(path, motion=False):
    previous.patch_duration_port(path, motion)
    text = path.read_text(encoding='utf-8').replace(previous.IDENTITY, IDENTITY)
    text = replace_once(text, '.trial_max_us=5000000U,.command_max=100U',
                        '.trial_max_us=8000000U,.command_max=160U')
    text = replace_once(text, '#define HALL_TRACE_CAPACITY 512U',
                        '#define HALL_TRACE_CAPACITY 768U')
    text = replace_once(text, 'static int motion_begin(void *u,float ref,float kp,float ki) {',
        '''/* Checked BEFORE queueing gains at the real PI boundary. Baseline may
 * always be restored. Probe cannot enter startup or survive its late window. */
int motor_td3_g431_response_gain_allowed(float kp,float ki,uint64_t now) {
    if(ki!=0.00144f) return 0;
    if(kp==0.003389f) return 1;
    if(kp!=0.00352456f || !motion_enabled || irq_fault ||
       !motor_td3_g431_trial_timing.started || !motor_td3_g431_trial_timing.run_seen ||
       motor_td3_g431_trial_timing.fault || rtDW.Motor_state!=4U ||
       now<motor_td3_g431_trial_timing.started_us) return 0;
    uint64_t elapsed=now-motor_td3_g431_trial_timing.started_us;
    /* 100 ms application allowance matches the existing wire expiry. */
    return elapsed>=5000000ULL && elapsed<6100000ULL;
}
static int motion_begin(void *u,float ref,float kp,float ki) {''')
    path.write_text(text, encoding='utf-8', newline='\n')
    gain = path.parent/'motor_td3_speedloop_can.c'
    text = gain.read_text(encoding='utf-8')
    text = replace_once(text, '    if(kp!=0.003389f || ki!=0.00144f) return 0;',
        '    extern int motor_td3_g431_response_gain_allowed(float,float,uint64_t);\n'
        '    if(!motor_td3_g431_response_gain_allowed(kp,ki,s->now_us)) return 0;')
    gain.write_text(text, encoding='utf-8', newline='\n')
    timing = path.parent/'motor_td3_trial_timing.h'
    text = timing.read_text(encoding='utf-8')
    text = replace_once(text, 'TD3_REVIEW_TOTAL_US 5000000ULL', 'TD3_REVIEW_TOTAL_US 8000000ULL')
    text = replace_once(text, 'TD3_REVIEW_CLOSED_US 2800000ULL', 'TD3_REVIEW_CLOSED_US 5800000ULL')
    timing.write_text(text, encoding='utf-8', newline='\n')


def build(args):
    args.can_pi = args.motion_can = args.baseline_duration_review = True
    old = original.MOTION_BUILD_ID, original.CAN_FILES, original.patch_can_port
    try:
        original.MOTION_BUILD_ID = IDENTITY
        original.CAN_FILES += ('motor_td3_trial_timing.c', 'motor_td3_trial_timing.h')
        original.patch_can_port = patch_port
        report = original.build(args)
    finally:
        original.MOTION_BUILD_ID, original.CAN_FILES, original.patch_can_port = old
    assert sum(report['image_sections_bytes'][k] for k in ('data','bss')) <= 28672, 'Reserve at least 4 KiB SRAM for stack'
    report['hall_trace_capacity'] = 768
    report['response_review'] = {
        'maximum_motion_seconds': 8, 'host_stop_seconds': 7.8,
        'startup_deadline_seconds': 2.6, 'closed_loop_deadline_seconds': 5.8,
        'maximum_batch_rounds': 2, 'maximum_batch_motion_seconds': 16,
        'minimum_cooldown_seconds': 30,
        'speed_ref_rpm': 1000, 'baseline_kp': .003389, 'fixed_ki': .00144,
        'probe_kp': .00352456, 'probe_source_elapsed_ms': [5000,6000],
        'probe_application_elapsed_ms': [5000,6100],
        'gain_gate_before_PI_publication': True,
        'command_max': 160, 'command_interval_ms': 50,
        'actor_allowed': False, 'physical_validation_passed': False,
        'ordinary_deployment_allowed': False, 'performance_claim_allowed': False,
        'temperature_gate_modified': False,
        'independent_cpu_stall_watchdog_integrated': False,
    }
    (Path(args.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc')
    p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
