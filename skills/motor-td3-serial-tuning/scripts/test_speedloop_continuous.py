"""Actual 24s adapter duration/gain/reference gates on a host HAL substitute."""
import argparse
import test_speedloop_response_review as old
import test_speedloop_motion_startup as original


def run(build,output,compiler):
    extra=old.EXTRA
    for a,b in [('8000','24000'),('5800200','21800200'),('5000999','3800999'),
                ('5001000','3801000'),('6100999','23100999'),('6101000','23101000'),
                ('5501000','6501000')]:extra=extra.replace(a,b)
    extra=extra.replace('j<=11','j<=331').replace('endpoint.pending.wire_seq=13','endpoint.pending.wire_seq=333')
    marker='    puts("{\\"passed\\":true,\\"adapter_checks\\":25}");return 0;'
    additions=r'''
    assert(endpoint.guard.limits.trial_max_us==24000000U);
    assert(endpoint.guard.limits.command_max==480U);
    fresh(50);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    ADC_offset=1;Vbus=24;motor_td3_g431_bus_sample();
    for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
    assert(motion_begin(0,1000,.003389f,.00144f));endpoint_ready=0;
    uint64_t start=host_us;
    for(unsigned ms=1;ms<23800;ms++) {
        host_us=start+(uint64_t)ms*1000;rtDW.Motor_state=ms<2201?3:4;
        main_seen_us=host_us;motor_td3_g431_adc_sample();motor_td3_g431_bus_sample();
        motor_td3_g431_tick_1ms();assert(!irq_fault && motion_enabled);
        unsigned phase=ms<4000?0:(ms-4000)%3600;
        float expected=(ms<4000||ms>=22000)?1000:phase<1200?1100:phase<2400?900:1000;
        assert(rtU.SpeedRef==expected);
    }
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"adapter_checks\":30}");return 0;
'''
    assert marker in extra;extra=extra.replace(marker,additions)
    h=original.HARNESS.replace('512U','832U').replace('i<620','i<900').replace('==620U','==900U').replace('108;i<900','68;i<900')
    h=h.replace('    test_primask=preempt_armed=preempt_suppressed=0;',
        '    memset(&motor_td3_g431_trial_timing,0,sizeof(motor_td3_g431_trial_timing));\n'
        '    test_primask=preempt_armed=preempt_suppressed=0;')
    h=h.replace('    puts("{\\"passed\\":true,\\"adapter_checks\\":12}");return 0;',extra)
    return original.run(build,output,compiler,duration_review=True,harness=h)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
