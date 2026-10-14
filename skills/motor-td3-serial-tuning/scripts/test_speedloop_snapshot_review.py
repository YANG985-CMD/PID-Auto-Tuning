"""Actual private v17 adapter timestamp regression tests, without hardware."""
import argparse
import test_speedloop_ki_review as previous

EXTRA = r'''
    fresh(92);motor_td3_telemetry captured;
    endpoint.guard.last_tick_us=1000;host_us=1750;
    endpoint.owner=1;endpoint.nonce=123;endpoint.guard.started_us=500;
    endpoint.guard.enabled=1;motion_enabled=1;
    pi_link.previous_error=0;Vbus=24;
    test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TD3_G431_PHASE_MASK;
    test_gpioa.MODER=(test_gpioa.MODER&~0x3f0000U)|0x2a0000U;
    test_gpio.MODER=(test_gpio.MODER&~0xfc000000U)|0xa8000000U;
    spd_kpki.spd_kp=endpoint.guard.kp;spd_kpki.spd_ki=endpoint.guard.ki;
    assert(actual_snapshot(0,&captured));
    assert(captured.t_us==1750 && captured.elapsed_ms==1.25f);
    uint8_t captured_bytes[TD3_CAN_MAX_PACKET];
    assert(motor_td3_can_make_telemetry(&endpoint,captured_bytes)==104);
    uint64_t encoded_time=0;
    for(unsigned i=0;i<8;i++) encoded_time|=(uint64_t)captured_bytes[32+i]<<(8*i);
    assert(encoded_time==1750 && encoded_time!=endpoint.guard.last_tick_us);
    uint32_t seq_before=endpoint.telemetry_seq;
    endpoint.guard.last_tick_us=1800;
    assert(!motor_td3_can_make_telemetry(&endpoint,captured_bytes));
    assert(endpoint.telemetry_seq==seq_before);
    endpoint.guard.last_tick_us=1000;endpoint.guard.t_apply_us=1800;
    assert(!motor_td3_can_make_telemetry(&endpoint,captured_bytes));
    assert(endpoint.telemetry_seq==seq_before);
    endpoint.guard.t_apply_us=0;preempt_armed=1;
    assert(actual_snapshot(0,&captured));
    assert(preempt_suppressed==1 && captured.t_us==1750);
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_lower_regressions_retained\":true,\"ki_checks\":15,\"snapshot_checks\":9}");return 0;
'''


def run(build, output, compiler):
    prior = previous.EXTRA
    marker = '    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15}");return 0;'
    assert prior.count(marker) == 1
    try:
        previous.EXTRA = prior.replace(marker, EXTRA)
        return previous.run(build, output, compiler)
    finally:
        previous.EXTRA = prior


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'output', 'compiler'):
        p.add_argument('--'+name, required=True)
    a = p.parse_args()
    run(a.build, a.output, a.compiler)
