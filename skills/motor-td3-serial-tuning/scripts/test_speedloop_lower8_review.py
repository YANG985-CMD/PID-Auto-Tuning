"""Exercise new exact gain through the actual PI/guard and all v18 regressions."""
import argparse
import test_speedloop_sampling_review as previous

EXTRA=r'''
    fresh(93);float lower8_integral=.3f;
    assert(!motor_td3_g431_response_gain_allowed(.003121269f,.00144f,6501000));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(motor_td3_g431_response_gain_allowed(.003121269f,.00144f,6501000));
    assert(!motor_td3_g431_response_gain_allowed(.003121269f,.001404f,6501000));
    assert(!motor_td3_g431_response_gain_allowed(.00311788f,.00144f,6501000));
    assert(!motor_td3_g431_response_gain_allowed(.003121269f,.00144f,3800999));
    assert(!motor_td3_g431_response_gain_allowed(.003121269f,.00144f,23101000));
    host_us=6501000;
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    assert(motor_td3_apply(&endpoint.guard,host_us,1,.003121269f,.00144f,200000));
    assert(motor_td3_apply(&endpoint.guard,host_us+50000,2,.003389f,.00144f,200000));
    pi_link.in_boundary=1;pi_link.integral=&lower8_integral;pi_link.now_us=host_us;
    pi_link.error=125;pi_link.reset=pi_link.applied=0;
    float u_before=spd_kpki.spd_kp*125+lower8_integral;
    endpoint.pending.wire_seq=1;endpoint.pending.command.lease_ms=200;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003121269f,.00144f));
    assert(spd_kpki.spd_kp==.003121269f && spd_kpki.spd_ki==.00144f);
    assert(fabsf(spd_kpki.spd_kp*125+lower8_integral-u_before)<2e-7f);
    pi_link.applied=0;pi_link.now_us+=50000;endpoint.pending.wire_seq=2;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.00325344f,.00144f));
    pi_link.applied=0;pi_link.now_us+=50000;endpoint.pending.wire_seq=3;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.00144f));
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_lower_regressions_retained\":true,\"ki_checks\":15,\"snapshot_checks\":9,\"sampling_checks\":2407,\"lower8_checks\":14}");return 0;
'''


def run(build,output,compiler):
    prior=previous.EXTRA
    marker='    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15,\\"snapshot_checks\\":9,\\"sampling_checks\\":2407}");return 0;'
    assert prior.count(marker)==1
    try:
        previous.EXTRA=prior.replace(marker,EXTRA)
        return previous.run(build,output,compiler)
    finally:previous.EXTRA=prior


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
