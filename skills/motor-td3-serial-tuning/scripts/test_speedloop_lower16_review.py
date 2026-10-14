"""Exercise v21 exact point, real guard slew rejection and PI continuity."""
import argparse
import test_speedloop_lower8_review as lower8
import test_speedloop_fixedref_review as previous

EXTRA=r'''
    fresh(94);float lower16_integral=.3f;
    assert(!motor_td3_g431_response_gain_allowed(.002856927f,.00144f,6501000));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;host_us=6501000;
    assert(motor_td3_g431_response_gain_allowed(.002856927f,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.002856927f,.001404f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.00285f,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.002856927f,.00144f,3800999));
    assert(!motor_td3_g431_response_gain_allowed(.002856927f,.00144f,23101000));
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    assert(!motor_td3_apply(&endpoint.guard,host_us,1,.002856927f,.00144f,200000));
    assert(endpoint.guard.fault && test_off());
    fresh(95);motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;host_us=6501000;
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    float stages[]={.003121269f,.002856927f,.003121269f,.003389f};
    for(unsigned i=0;i<4;i++) {
        uint64_t tick=host_us+50000*i;
        assert(motor_td3_apply(&endpoint.guard,tick,i+1,stages[i],.00144f,200000));
        pi_link.in_boundary=1;pi_link.integral=&lower16_integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+lower16_integral;
        endpoint.pending.wire_seq=i+1;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,stages[i],.00144f));
        assert(spd_kpki.spd_kp==stages[i] && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+lower16_integral-before)<3e-7f);
    }
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_lower_regressions_retained\":true,\"ki_checks\":15,\"snapshot_checks\":9,\"sampling_checks\":2407,\"lower8_checks\":14,\"lower16_staged_and_direct_rejection\":true}");return 0;
'''

def run(build,output,compiler):
    prior=lower8.EXTRA
    marker='    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15,\\"snapshot_checks\\":9,\\"sampling_checks\\":2407,\\"lower8_checks\\":14}");return 0;'
    assert prior.count(marker)==1
    try:
        lower8.EXTRA=prior.replace(marker,EXTRA)
        return previous.run(build,output,compiler)
    finally:lower8.EXTRA=prior

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
