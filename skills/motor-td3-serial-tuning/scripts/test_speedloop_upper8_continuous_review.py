"""Continuous range boundaries and actual PI commits, retained v24 fault tests."""
import argparse
import json
from pathlib import Path
import test_speedloop_upper8_review as previous
import test_speedloop_lower_proposal as target

EXTRA=r'''
    fresh(98);motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;host_us=6501000;
    assert(!motor_td3_g431_response_gain_allowed(NAN,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(INFINITY,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.0036f,NAN,host_us));
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.00366012f,INFINITY),.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.003389f,-INFINITY),.00144f,host_us));
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    float continuous_integral=.3f;
    for(unsigned i=1;i<=2001;i++) {
        float kp=.003389f+(.00366012f-.003389f)*(i<=1001?(i-1)/1000.f:(2001-i)/1000.f);
        uint64_t tick=host_us+1000*i;
        assert(motor_td3_g431_response_gain_allowed(kp,.00144f,tick));
        assert(!motor_td3_g431_response_gain_allowed(kp,.0014401f,tick));
        if(kp!=.003389f) {
            assert(!motor_td3_g431_response_gain_allowed(kp,.00144f,3800999));
            assert(!motor_td3_g431_response_gain_allowed(kp,.00144f,23101000));
        }
        assert(motor_td3_apply(&endpoint.guard,tick,i,kp,.00144f,200000));
        /* Reset the test-only command counter; production limit is checked by retained tests. */
        endpoint.guard.commands=0;
        pi_link.in_boundary=1;pi_link.integral=&continuous_integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+continuous_integral;
        endpoint.pending.wire_seq=i;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,kp,.00144f));
        assert(spd_kpki.spd_kp==kp && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+continuous_integral-before)<3e-7f);
    }
    irq_fault=1;
    assert(!motor_td3_g431_response_gain_allowed(.0036f,.00144f,host_us));
    irq_fault=0;motor_td3_g431_trial_timing.fault=1;
    assert(!motor_td3_g431_response_gain_allowed(.0036f,.00144f,host_us));
    motor_td3_g431_trial_timing.fault=0;rtDW.Motor_state=3;
    assert(!motor_td3_g431_response_gain_allowed(.0036f,.00144f,host_us));
    motor_td3_g431_disable();assert(test_off());
'''

def run(build,output,compiler):
    base_run=target.BASE_RUN
    def checked(b,o,c,duration_review=False,harness=None):
        for gain in ('.0036f','.00345f'):
            old=f'assert(!motor_td3_g431_response_gain_allowed({gain},.00144f,6501000));'
            if harness.count(old)!=1:raise ValueError('Old interior point rejection contract not found')
            harness=harness.replace(old,f'assert(motor_td3_g431_response_gain_allowed({gain},.00144f,6501000));')
        marker='    puts("{\\"passed\\":true'
        if harness.count(marker)!=1:raise ValueError('Retained regression footer missing')
        harness=harness.replace(marker,EXTRA+marker)
        return base_run(b,o,c,duration_review=duration_review,harness=harness)
    try:
        target.BASE_RUN=checked
        result=previous.run(build,output,compiler)
    finally:target.BASE_RUN=base_run
    result['continuous_upper8_checks']=dict(passed=True,actual_continuous_commits=2001,
        exact_float32_readback=True,bumpless_PI_checked=True,range_ulp_nan_ki_time_fault_checks=True,
        retained_stop_and_guard_checks=True,old_contract_replaced_only_for_new_interior_point=True,
        physical_validation=False,hardware_accessed=False)
    (Path(output)/'continuous-upper8-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
