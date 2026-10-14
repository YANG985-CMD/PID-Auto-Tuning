"""Actual adapter reference schedule, gain window and shutdown tests; no hardware."""
import argparse
import test_speedloop_response_review as previous
from build_speedloop_excitation_review import IDENTITY


def run(build,output,compiler):
    extra=previous.EXTRA
    for old,new in [('5000999','3800999'),('5001000','3801000'),
                    ('6100999','7100999'),('6101000','7101000'),('5501000','6501000')]:
        extra=extra.replace(old,new)
    anchor='    puts("{\\"passed\\":true,\\"adapter_checks\\":25}");return 0;'
    assert extra.count(anchor)==1
    additions=r'''
    assert(motor_td3_g431_excitation_reference(3999999)==1000);
    assert(motor_td3_g431_excitation_reference(4000000)==1100);
    assert(motor_td3_g431_excitation_reference(5199999)==1100);
    assert(motor_td3_g431_excitation_reference(5200000)==900);
    assert(motor_td3_g431_excitation_reference(6400000)==1000);
    fresh(50);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    ADC_offset=1;Vbus=24;motor_td3_g431_bus_sample();
    for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
    assert(motion_begin(0,1000,.003389f,.00144f));endpoint_ready=0;
    uint64_t reference_start=host_us;
    for(unsigned ms=1;ms<7800;ms++) {
        host_us=reference_start+(uint64_t)ms*1000;
        rtDW.Motor_state=ms<2201?3:4;
        main_seen_us=host_us;motor_td3_g431_adc_sample();motor_td3_g431_bus_sample();
        motor_td3_g431_tick_1ms();
        assert(!irq_fault && motion_enabled);
        float expected=ms<4000?1000:ms<5200?1100:ms<6400?900:1000;
        assert(rtU.SpeedRef==expected);
    }
    motor_td3_g431_disable();assert(test_off() && !motion_enabled);
    puts("{\"passed\":true,\"adapter_checks\":31}");return 0;
'''
    extra=extra.replace(anchor,additions)
    old=previous.EXTRA,previous.IDENTITY
    try:
        previous.EXTRA=extra;previous.IDENTITY=IDENTITY
        return previous.run(build,output,compiler)
    finally:previous.EXTRA,previous.IDENTITY=old


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
