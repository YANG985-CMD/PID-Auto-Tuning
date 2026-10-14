"""Exercise new exact gain, unchanged physical guard and bumpless PI boundary."""
import argparse
import json
from pathlib import Path
import test_speedloop_sampling_v22 as previous
import test_speedloop_lower16_review as lower16

EXTRA=r'''
    fresh(96);
    assert(!motor_td3_g431_response_gain_allowed(.00366012f,.00144f,6501000));
    motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;host_us=6501000;
    assert(motor_td3_g431_response_gain_allowed(.00366012f,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.00366012f,.001476f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.00366013f,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.00366012f,.00144f,3800999));
    assert(!motor_td3_g431_response_gain_allowed(.00366012f,.00144f,23101000));
    float upper8_integral=.3f;
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    float upper8_stages[]={.00352456f,.00366012f,.00352456f,.003389f};
    for(unsigned i=0;i<4;i++) {
        uint64_t tick=host_us+50000*i;
        assert(motor_td3_apply(&endpoint.guard,tick,i+1,upper8_stages[i],.00144f,200000));
        pi_link.in_boundary=1;pi_link.integral=&upper8_integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+upper8_integral;
        endpoint.pending.wire_seq=i+1;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,upper8_stages[i],.00144f));
        assert(spd_kpki.spd_kp==upper8_stages[i] && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+upper8_integral-before)<3e-7f);
    }
    motor_td3_g431_disable();assert(test_off());
'''

def run(build,output,compiler):
    prior=lower16.EXTRA;marker='    puts("{\\"passed\\":true'
    if prior.count(marker)!=1:raise ValueError('Retained guard test footer missing')
    try:
        lower16.EXTRA=prior.replace(marker,EXTRA+marker)
        result=previous.run(build,output,compiler)
    finally:lower16.EXTRA=prior
    result['upper8_checks']=dict(new_point_exact_only=True,ki_fixed=True,
        startup_and_end_time_rejected=True,actual_pi_bumpless_bridge_checked=True,
        retained_stop_and_guard_checks=True,hardware_accessed=False)
    (Path(output)/'upper8-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
