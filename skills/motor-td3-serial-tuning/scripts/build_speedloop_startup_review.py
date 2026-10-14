"""Offline five-second baseline with frozen startup Hall and 1ms state traces.

Control and protection are unchanged. This records the open-to-Hall handover,
which the ordinary last-N Hall ring overwrites before the trial ends.
"""
import argparse,json
from pathlib import Path
import build_speedloop_duration_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-startup-trace-5s-v9'
BASE_PATCH=previous.patch_duration_port


def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    s=path.read_text(encoding='utf-8')
    s=replace_once(s,'volatile uint32_t motor_td3_g431_hall_edge_count;', '''volatile uint32_t motor_td3_g431_hall_edge_count;
volatile hall_edge_record motor_td3_g431_startup_hall[128];
volatile uint32_t motor_td3_g431_startup_hall_count,motor_td3_g431_startup_hall_overflow;
typedef struct {
    uint64_t t_us;
    float speed_rpm,hall_theta,open_theta,iq_reference,pi_integral;
    uint32_t model_stage;
} startup_state_record;
_Static_assert(sizeof(startup_state_record)==32,"Frozen startup trace layout");
volatile startup_state_record motor_td3_g431_startup_states[128];
volatile uint32_t motor_td3_g431_startup_state_count,motor_td3_g431_startup_state_overflow;''')
    anchor='        now_us,(unsigned)rtDW.Motor_state)) motor_td3_g431_fault_irq();'
    s=replace_once(s,anchor,anchor+'''
    if(motion_enabled && motor_td3_g431_trial_timing.started &&
       now_us>=motor_td3_g431_trial_timing.started_us) {
        uint64_t elapsed=now_us-motor_td3_g431_trial_timing.started_us;
        if(elapsed>=2150000ULL && elapsed<2270000ULL) {
            uint32_t count=motor_td3_g431_startup_state_count;
            if(count<128U) {
                motor_td3_g431_startup_states[count]=(startup_state_record){now_us,HallSpeed,
                    rtU.theta,rtDW.DiscreteTimeIntegrator1_DSTATE,rtDW.Merge1,
                    rtDW.Integrator_DSTATE_h,(uint32_t)rtDW.Motor_state};
                motor_td3_g431_startup_state_count=count+1U;
            } else ++motor_td3_g431_startup_state_overflow;
        }
    }''')
    s=replace_once(s,'    ++motor_td3_g431_hall_edge_count;', '''    if(motor_td3_g431_trial_timing.started && n>=motor_td3_g431_trial_timing.started_us) {
        uint64_t elapsed=n-motor_td3_g431_trial_timing.started_us;
        if(elapsed>=2000000ULL && elapsed<2400000ULL) {
            uint32_t count=motor_td3_g431_startup_hall_count;
            if(count<128U) {
                motor_td3_g431_startup_hall[count]=
                    motor_td3_g431_hall_edges[motor_td3_g431_hall_edge_count%HALL_TRACE_CAPACITY];
                motor_td3_g431_startup_hall_count=count+1U;
            } else ++motor_td3_g431_startup_hall_overflow;
        }
    }
    ++motor_td3_g431_hall_edge_count;''')
    path.write_text(s,encoding='utf-8',newline='\n')


def build(args):
    old=previous.IDENTITY,previous.original_patch
    # previous.build dispatches patch_duration_port; replace it only for this build.
    saved=previous.patch_duration_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_duration_port=patch_port
        report=previous.build(args)
    finally:
        previous.IDENTITY,previous.original_patch=old;previous.patch_duration_port=saved
    assert sum(report['image_sections_bytes'][k] for k in ('data','bss'))<=28672
    report['startup_review']=dict(maximum_motion_seconds=5,host_stop_seconds=4.8,
        fixed_baseline_only=True,actor_allowed=False,hall_window_us=[2000000,2400000],
        state_window_us=[2150000,2270000],hall_capacity=128,state_capacity=128,
        state_record_bytes=32,control_modified=False,physical_validation_passed=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False)
    report['hall_trace_capacity']=512
    (Path(args.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
