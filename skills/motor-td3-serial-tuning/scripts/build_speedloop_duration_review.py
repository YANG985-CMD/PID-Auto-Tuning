"""Offline build of a SINGLE five-second baseline review. Never accesses hardware.

Keeps motion-v5 and its exact-image tools unchanged. The distinct v6 identity
cannot be accepted by their live runners. Approval and board verification are
still required before any physical run; this does not open deployment gates.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_pi_integration as original
from build_g431_locked_foc import replace_once

IDENTITY = 'g431-speedloop-pi-baseline-5s-v6'


def patch_duration_port(path, motion=False):
    original_patch(path, motion)
    if not motion: raise ValueError('Duration review needs the explicit motion adapter')
    text = path.read_text(encoding='utf-8')
    text = text.replace('g431-speedloop-pi-motion-v5', IDENTITY)
    text = replace_once(text, '#include "motor_td3_speedloop_pi_bind.h"',
        '#include "motor_td3_speedloop_pi_bind.h"\n'
        '#include "motor_td3_trial_timing.h"\n'
        'motor_td3_trial_timing motor_td3_g431_trial_timing;')
    text = replace_once(text, '.trial_max_us=3000000U,.command_max=60U',
                         '.trial_max_us=5000000U,.command_max=100U')
    text = replace_once(text, '    /* Called with interrupts serialized at the generated PI boundary.',
        '    if(ref!=1000.0f || kp!=0.003389f || ki!=0.00144f ||\n'
        '       !motor_td3_trial_timing_begin(&motor_td3_g431_trial_timing,clock_us())) {\n'
        '        motor_td3_g431_disable(); return 0;\n'
        '    }\n'
        '    /* Called with interrupts serialized at the generated PI boundary.')
    text = replace_once(text, '    if(motor_td3_g431_break_seen()) motor_td3_g431_fault_irq();',
        '    if(motion_enabled && !motor_td3_trial_timing_tick(&motor_td3_g431_trial_timing,\n'
        '        now_us,(unsigned)rtDW.Motor_state)) motor_td3_g431_fault_irq();\n'
        '    if(motor_td3_g431_break_seen()) motor_td3_g431_fault_irq();')
    path.write_text(text, encoding='utf-8', newline='\n')
    gain_path = path.parent / 'motor_td3_speedloop_can.c'
    text = gain_path.read_text(encoding='utf-8')
    text = replace_once(text, '    uint64_t lease=(uint64_t)cmd->command.lease_ms*1000U;',
        '    uint64_t lease=(uint64_t)cmd->command.lease_ms*1000U;\n'
        '#ifdef MOTOR_TD3_BASELINE_DURATION_REVIEW\n'
        '    /* Reject before publishing either gain to the real PI. */\n'
        '    if(kp!=0.003389f || ki!=0.00144f) return 0;\n'
        '#endif')
    gain_path.write_text(text, encoding='utf-8', newline='\n')


original_patch = original.patch_can_port


def build(args):
    args.can_pi = args.motion_can = args.baseline_duration_review = True
    old_id, old_files, old_patch = original.MOTION_BUILD_ID, original.CAN_FILES, original.patch_can_port
    try:
        original.MOTION_BUILD_ID = IDENTITY
        original.CAN_FILES += ('motor_td3_trial_timing.c', 'motor_td3_trial_timing.h')
        original.patch_can_port = patch_duration_port
        report = original.build(args)
    finally:
        original.MOTION_BUILD_ID, original.CAN_FILES, original.patch_can_port = old_id, old_files, old_patch
    report['duration_review'] = {
        'mode': 'single fixed baseline PI; no Actor or gain exploration',
        'maximum_motion_seconds': 5, 'host_stop_seconds': 4.8,
        'startup_deadline_seconds': 2.6, 'closed_loop_deadline_seconds': 2.8,
        'closed_loop_clock_source': 'generated rtDW.Motor_state == 4, latched by 1ms MCU tick',
        'expected_closed_loop_observation_seconds': 2.6,
        'kp': .003389, 'ki': .00144, 'speed_ref_rpm': 1000,
        'gain_change_rejected_before_PI_publication': True,
        'command_max': 100, 'command_interval_ms': 50,
        'approval_required': True, 'physical_validation_passed': False,
        'ordinary_deployment_allowed': False, 'performance_claim_allowed': False,
        'temperature_gate_modified': False,
        'independent_cpu_stall_watchdog_integrated': False,
    }
    (Path(args.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'arm-bin'): parser.add_argument('--'+name, required=True)
    parser.add_argument('--compiler', default='gcc')
    parser.add_argument('--temp-root', default='E:/simulink/_codex_tmp')
    build(parser.parse_args())
