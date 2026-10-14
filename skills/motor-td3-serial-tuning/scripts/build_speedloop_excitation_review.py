"""Offline scripted-reference data-collection image. No Actor or hardware access.

Adds repeatable 1000/1100/900/1000 rpm steps after startup. 800/1200 rpm
remain excluded. Original FOC and all existing physical trip limits remain.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_response_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-excitation-8s-v8'
BASE_PATCH=previous.patch_port


def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'return elapsed>=5000000ULL && elapsed<6100000ULL;',
        'return elapsed>=3800000ULL && elapsed<7100000ULL;')
    text=replace_once(text,'static int motion_begin(void *u,float ref,float kp,float ki) {',
        '''float motor_td3_g431_excitation_reference(uint64_t elapsed) {
    if(elapsed<4000000ULL) return 1000.0f;
    if(elapsed<5200000ULL) return 1100.0f;
    if(elapsed<6400000ULL) return 900.0f;
    return 1000.0f;
}
static int motion_begin(void *u,float ref,float kp,float ki) {''')
    anchor='        now_us,(unsigned)rtDW.Motor_state)) motor_td3_g431_fault_irq();'
    text=replace_once(text,anchor,anchor+'''
    /* Tick is already serialized against ADC/PI and telemetry snapshots.
     * A failed timing guard disables motion before any reference update. */
    if(motion_enabled && motor_td3_g431_trial_timing.run_seen && rtDW.Motor_state==4U)
        rtU.SpeedRef=motor_td3_g431_excitation_reference(
            now_us-motor_td3_g431_trial_timing.started_us);''')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(args):
    old=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        report=previous.build(args)
    finally:
        previous.IDENTITY,previous.patch_port=old
    report['response_review'].update(probe_source_elapsed_ms=[3900,7000],
                                    probe_application_elapsed_ms=[3800,7100])
    report['excitation_review']=dict(reference_schedule_ms_rpm=[[0,1000],[4000,1100],[5200,900],[6400,1000]],
        reference_owner='MCU serialized 1ms tick; telemetry reports actual rtU.SpeedRef',
        initial_reference_rpm=1000,minimum_reference_rpm=900,maximum_reference_rpm=1100,
        held_out_reference_rpm=[800,1200],maximum_motion_seconds=8,host_stop_seconds=7.8,
        maximum_batch_motion_seconds=16,actor_allowed=False,physical_validation_passed=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False,temperature_gate_modified=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
