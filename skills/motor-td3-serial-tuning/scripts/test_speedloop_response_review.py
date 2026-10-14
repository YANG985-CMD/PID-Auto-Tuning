"""Test the actual eight-second review adapter/model without hardware."""
import argparse
import json
from pathlib import Path
import test_speedloop_motion_startup as original
from build_speedloop_response_review import IDENTITY
HALL_TRACE_CAPACITY = 768

EXTRA = r'''
    /* Startup probes and all Ki changes must be rejected before PI publication. */
    fresh(20);
    float integral=0,old_kp=spd_kpki.spd_kp,old_ki=spd_kpki.spd_ki;
    pi_link.in_boundary=1;pi_link.integral=&integral;
    pi_link.now_us=host_us;pi_link.error=0;
    assert(!endpoint.hooks.apply(endpoint.hooks.user,.00352456f,.00144f));
    assert(spd_kpki.spd_kp==old_kp&&spd_kpki.spd_ki==old_ki);
    assert(!endpoint.hooks.apply(endpoint.hooks.user,.003389f,.001476f));
    assert(spd_kpki.spd_kp==old_kp&&spd_kpki.spd_ki==old_ki);

    /* Exercise timing through the actual adapter's SysTick and hardware-off path.
     * Suspend the protocol tick to isolate this extra deadline from its lease. */
    for(unsigned scenario=0;scenario<4;scenario++) {
        fresh(30+scenario);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
        ADC_offset=1;Vbus=24;motor_td3_g431_bus_sample();
        for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
        assert(motion_begin(0,1000,.003389f,.00144f));
        endpoint_ready=0;
        uint64_t start=host_us;
        for(unsigned ms=1;ms<=8000;ms++) {
            host_us=start+(uint64_t)ms*1000;
            rtDW.Motor_state=(scenario==0 || ms<2201)?3:4;
            if(scenario==2 && ms>=2300) rtDW.Motor_state=3;
            main_seen_us=host_us;motor_td3_g431_adc_sample();motor_td3_g431_bus_sample();
            if(scenario==3 && ms==2300) host_us-=2000;
            motor_td3_g431_tick_1ms();
            if(irq_fault) {
                assert(test_off());
                assert(ms==(scenario==0?2600:scenario==1?8000:2300));
                assert(motor_td3_g431_trial_timing.fault==
                    (scenario==0?TD3_TIMING_STARTUP:scenario==1?TD3_TIMING_TOTAL:
                     scenario==2?TD3_TIMING_REGRESSION:TD3_TIMING_CLOCK));
                break;
            }
            assert(ms<8000);
        }
        assert(irq_fault && !motion_enabled && test_off());
        assert(!motor_td3_trial_timing_begin(&motor_td3_g431_trial_timing,host_us+1));
    }

    /* Probe phase, stage and exact gains are enforced before real PI writes. */
    fresh(40);motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;
    motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(!motor_td3_g431_response_gain_allowed(.00352456f,.00144f,5000999));
    assert(motor_td3_g431_response_gain_allowed(.00352456f,.00144f,5001000));
    assert(motor_td3_g431_response_gain_allowed(.00352456f,.00144f,6100999));
    assert(!motor_td3_g431_response_gain_allowed(.00352456f,.00144f,6101000));
    rtDW.Motor_state=3;
    assert(!motor_td3_g431_response_gain_allowed(.00352456f,.00144f,5501000));
    rtDW.Motor_state=4;
    assert(!motor_td3_g431_response_gain_allowed(.00352456f,.001476f,5501000));
    assert(!motor_td3_g431_response_gain_allowed(.0036f,.00144f,5501000));
    pi_link.in_boundary=1;pi_link.integral=&integral;pi_link.now_us=5501000;
    pi_link.error=0;pi_link.reset=pi_link.applied=0;
    endpoint.pending.wire_seq=1;endpoint.pending.command.lease_ms=200;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.00352456f,.00144f));
    assert(spd_kpki.spd_kp==.00352456f && spd_kpki.spd_ki==.00144f);
    /* Keep the original lease alive while advancing through the probe. */
    for(unsigned j=1;j<=11;j++) {
        pi_link.applied=0;pi_link.now_us=5501000+(uint64_t)j*50000;
        endpoint.pending.wire_seq=1+j;
        assert(endpoint.hooks.apply(endpoint.hooks.user,.00352456f,.00144f));
    }
    pi_link.applied=0;pi_link.now_us=6101000;endpoint.pending.wire_seq=13;
    assert(!endpoint.hooks.apply(endpoint.hooks.user,.00352456f,.00144f));
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.00144f));
    assert(spd_kpki.spd_kp==.003389f);

    motor_td3_trial_timing timing={0};
    assert(motor_td3_trial_timing_begin(&timing,100));
    assert(motor_td3_trial_timing_tick(&timing,200,4));
    assert(!motor_td3_trial_timing_tick(&timing,5800200,4));
    assert(timing.fault==TD3_TIMING_CLOSED);
    puts("{\"passed\":true,\"adapter_checks\":25}");return 0;
'''


def run(build, output, compiler):
    report=json.loads((Path(build)/'summary.json').read_text(encoding='utf-8'))
    assert report['build_id']==IDENTITY and report['response_review']['maximum_motion_seconds']==8
    harness=original.HARNESS.replace('512U',f'{HALL_TRACE_CAPACITY}U').replace('i<620','i<900').replace('==620U','==900U').replace('108;i<900',f'{900-HALL_TRACE_CAPACITY};i<900').replace('    test_primask=preempt_armed=preempt_suppressed=0;',
        '    memset(&motor_td3_g431_trial_timing,0,sizeof(motor_td3_g431_trial_timing));\n'
        '    test_primask=preempt_armed=preempt_suppressed=0;')
    marker='    puts("{\\"passed\\":true,\\"adapter_checks\\":12}");return 0;'
    assert harness.count(marker)==1
    harness=harness.replace(marker,EXTRA)
    return original.run(build,output,compiler,duration_review=True,harness=harness)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();run(args.build,args.output,args.compiler)
