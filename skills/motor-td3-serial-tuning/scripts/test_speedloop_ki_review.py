"""Actual PI and guard Ki checks with host HAL substitutes; no hardware."""
import argparse
import test_speedloop_lower_proposal as previous

EXTRA = r'''
    fresh(91);float ki_integral=.3f;
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.001404f,4000000));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.001404f,3800999));
    assert(motor_td3_g431_response_gain_allowed(.003389f,.001404f,3801000));
    assert(motor_td3_g431_response_gain_allowed(.003389f,.001476f,23100999));
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.001476f,23101000));
    assert(!motor_td3_g431_response_gain_allowed(.00325344f,.001404f,6501000));
    assert(!motor_td3_g431_response_gain_allowed(.003389f,.0015f,6501000));
    pi_link.in_boundary=1;pi_link.integral=&ki_integral;pi_link.now_us=6501000;
    pi_link.error=125.0f;pi_link.reset=pi_link.applied=0;
    endpoint.pending.wire_seq=1;endpoint.pending.command.lease_ms=200;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.001404f));
    assert(spd_kpki.spd_kp==.003389f && spd_kpki.spd_ki==.001404f);
    assert(ki_integral==.3f); /* Integrator output must not be rescaled by Ki. */
    pi_link.applied=0;pi_link.now_us+=50000;endpoint.pending.wire_seq=2;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.001476f));
    assert(spd_kpki.spd_kp==.003389f && spd_kpki.spd_ki==.001476f && ki_integral==.3f);
    pi_link.applied=0;pi_link.now_us+=50000;endpoint.pending.wire_seq=3;
    assert(endpoint.hooks.apply(endpoint.hooks.user,.003389f,.00144f));
    assert(ki_integral==.3f && spd_kpki.spd_ki==.00144f);
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_lower_regressions_retained\":true,\"ki_checks\":15}");return 0;
'''


def run(build, output, compiler):
    original = previous.BASE_RUN
    def checked(b, o, c, duration_review=False, harness=None):
        marker = '    puts("{\\"passed\\":true,\\"adapter_checks\\":54}");return 0;'
        assert harness.count(marker) == 1
        return original(b, o, c, duration_review=duration_review, harness=harness.replace(marker, EXTRA))
    try:
        previous.BASE_RUN = checked
        return previous.run(build, output, compiler)
    finally:
        previous.BASE_RUN = original


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'output', 'compiler'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    run(args.build, args.output, args.compiler)
