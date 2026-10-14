"""Actual guard/PI check for a not-yet-flashed Ki proposal; offline only."""
import argparse
import test_speedloop_lower16_review as lower16
import test_speedloop_sampling_v22 as previous

EXTRA=r'''
    fresh(96);float ki20_integral=.3f;host_us=6501000;
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.00115632f,host_us));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(motor_td3_g431_response_gain_allowed(.003389f,.00115632f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.00115632f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.00115f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.00115632f,3800999));
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.00115632f,23101000));
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    assert(!motor_td3_apply(&endpoint.guard,host_us,1,.003389f,.00115632f,200000));
    assert(endpoint.guard.fault && test_off());
    fresh(97);motion_enabled=1;rtDW.Motor_state=4;host_us=6501000;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    float kis[]={.00129744f,.00115632f,.00129744f,.00144f};
    for(unsigned i=0;i<4;i++) {
        uint64_t tick=host_us+50000*i;
        assert(motor_td3_apply(&endpoint.guard,tick,i+1,.003389f,kis[i],200000));
        pi_link.in_boundary=1;pi_link.integral=&ki20_integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+ki20_integral;
        endpoint.pending.wire_seq=i+1;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,kis[i]));
        assert(spd_kpki.spd_kp==.003389f && spd_kpki.spd_ki==kis[i]);
        assert(fabsf(spd_kpki.spd_kp*125+ki20_integral-before)<3e-7f);
    }
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_regressions_retained\":true,\"ki20_staged_guard_and_integral_checks\":true,\"direct_jump_rejected\":true}");return 0;
'''

def run(build,output,compiler):
    prior=lower16.EXTRA
    marker='    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15,\\"snapshot_checks\\":9,\\"sampling_checks\\":2407,\\"lower8_checks\\":14,\\"lower16_staged_and_direct_rejection\\":true}");return 0;'
    assert prior.count(marker)==1
    try:
        lower16.EXTRA=prior.replace(marker,EXTRA)
        return previous.run(build,output,compiler)
    finally:lower16.EXTRA=prior

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','output','compiler'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
