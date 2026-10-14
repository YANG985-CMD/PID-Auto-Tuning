"""Host-only check of proposed lower gain. Does not grant physical approval."""
import argparse
import test_speedloop_interior as previous
import test_speedloop_motion_startup as original

BASE_RUN=original.run
EXTRA=r'''
    fresh(90);float lower_integral=.3f;
    float lower_before=.003389f*125.0f+lower_integral;
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.00144f,4000000));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.00144f,3800999));
    assert(motor_td3_g431_response_gain_allowed(.00325344f,.00144f,3801000));
    assert(motor_td3_g431_response_gain_allowed(.00325344f,.00144f,23100999));
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.00144f,23101000));
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.001476f,6501000));
    assert(!motor_td3_g431_response_gain_allowed(.0032f,.00144f,6501000));
    pi_link.in_boundary=1;pi_link.integral=&lower_integral;pi_link.now_us=6501000;
    pi_link.error=125.0f;pi_link.reset=pi_link.applied=0;
    endpoint.pending.wire_seq=1;endpoint.pending.command.lease_ms=200;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.00325344f,.00144f));
    assert(spd_kpki.spd_kp==.00325344f && spd_kpki.spd_ki==.00144f);
    assert(fabsf(spd_kpki.spd_kp*125.0f+lower_integral-lower_before)<2e-7f);
    pi_link.applied=0;pi_link.now_us+=50000;endpoint.pending.wire_seq=2;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.00144f));
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"adapter_checks\":54}");return 0;
'''


def run(build,output,compiler):
    def checked(b,o,c,duration_review=False,harness=None):
        marker='    puts("{\\"passed\\":true,\\"adapter_checks\\":42}");return 0;'
        assert harness.count(marker)==1
        return BASE_RUN(b,o,c,duration_review=duration_review,harness=harness.replace(marker,EXTRA))
    saved=previous.BASE_RUN
    try:previous.BASE_RUN=checked;return previous.run(build,output,compiler)
    finally:previous.BASE_RUN=saved


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
