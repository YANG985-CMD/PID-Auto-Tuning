"""Exercise the actual v9 frozen trace and five-second stop path without hardware."""
import argparse
import test_speedloop_duration_review as previous
from build_speedloop_startup_review import IDENTITY


def run(build,output,compiler):
    original=previous.original.HARNESS
    extra=previous.EXTRA
    marker='    test_primask=preempt_armed=preempt_suppressed=0;'
    harness=original.replace(marker,'''    memset(&hall_clock,0,sizeof(hall_clock));motor_td3_g431_hall_edge_count=0;
    motor_td3_g431_startup_hall_count=motor_td3_g431_startup_hall_overflow=0;
    motor_td3_g431_startup_state_count=motor_td3_g431_startup_state_overflow=0;
'''+marker)
    anchor='    puts("{\\"passed\\":true,\\"adapter_checks\\":19}");return 0;'
    assert extra.count(anchor)==1
    test=r'''
    fresh(50);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    ADC_offset=1;Vbus=24;motor_td3_g431_bus_sample();
    for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
    assert(motion_begin(0,1000,.003389f,.00144f));endpoint_ready=0;
    uint64_t trace_start=host_us;unsigned hall_index=0;
    const uint8_t hall_order[6]={5,4,6,2,3,1};
    for(unsigned ms=1;ms<=2400;ms++) {
        host_us=trace_start+(uint64_t)ms*1000;
        rtDW.Motor_state=ms<2201?3:4;
        rtU.theta=.5f;rtDW.DiscreteTimeIntegrator1_DSTATE=1.7f;
        rtDW.Merge1=1;rtDW.Integrator_DSTATE_h=.3f;
        if(ms%5==0) assert(motor_td3_g431_hall_capture(16000,hall_order[(hall_index++)%6]));
        main_seen_us=host_us;motor_td3_g431_adc_sample();motor_td3_g431_bus_sample();
        motor_td3_g431_tick_1ms();assert(!irq_fault && motion_enabled);
    }
    assert(motor_td3_g431_startup_hall_count==80 && !motor_td3_g431_startup_hall_overflow);
    assert(motor_td3_g431_startup_state_count==120 && !motor_td3_g431_startup_state_overflow);
    for(unsigned i=0;i<120;i++) {
        startup_state_record v=motor_td3_g431_startup_states[i];
        assert(v.t_us==trace_start+(2150ULL+i)*1000 && v.hall_theta==.5f && v.open_theta==1.7f);
        assert(v.iq_reference==1 && v.pi_integral==.3f && v.speed_rpm==1000);
        assert(v.model_stage==(i<51?3U:4U));
    }
    motor_td3_g431_disable();host_us+=1000;motor_td3_g431_tick_1ms();
    assert(test_off() && motor_td3_g431_startup_state_count==120 && motor_td3_g431_startup_hall_count==80);
    puts("{\"passed\":true,\"adapter_checks\":23}");return 0;
'''
    try:
        previous.original.HARNESS=harness;previous.EXTRA=extra.replace(anchor,test)
        old=previous.IDENTITY;previous.IDENTITY=IDENTITY
        return previous.run(build,output,compiler)
    finally:
        previous.original.HARNESS=original;previous.EXTRA=extra;previous.IDENTITY=old


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
