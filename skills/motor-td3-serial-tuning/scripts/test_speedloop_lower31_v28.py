"""All v27 checks plus new staged lower endpoint; host only."""
import argparse,hashlib,json
from pathlib import Path
import test_speedloop_bidirectional_v27 as previous
import test_speedloop_lower16_review as lower16
from build_speedloop_lower31_v28 import IDENTITY
BASE=previous.run
EXTRA=r'''
    {
    fresh(201);motion_enabled=1;rtDW.Motor_state=4;host_us=6501000;
    spd_kpki.spd_kp=.003389f;spd_kpki.spd_ki=.00144f; /* Fresh fixture baseline, matching BEGIN. */
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.002328243f,-INFINITY),.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.00366012f,INFINITY),.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(NAN,.00144f,host_us));
    float stages[]={.00325344f,.003121269f,.002989098f,.002856927f,.002724756f,.002592585f,.002460414f,.002328243f};
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));float integral=.3f;
    for(unsigned j=0;j<16;j++) {
        float kp=j<8?stages[j]:j==15?.003389f:stages[14-j];uint64_t tick=host_us+1000*j;
        assert(fabsf(kp-spd_kpki.spd_kp)<=.00013556f+1e-9f);
        assert(motor_td3_g431_response_gain_allowed(kp,.00144f,tick));
        assert(motor_td3_apply(&endpoint.guard,tick,j+1,kp,.00144f,200000));
        pi_link.in_boundary=1;pi_link.integral=&integral;pi_link.now_us=tick;pi_link.error=125;
        pi_link.reset=pi_link.applied=0;float before=spd_kpki.spd_kp*125+integral;
        endpoint.pending.wire_seq=j+1;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,kp,.00144f));
        assert(spd_kpki.spd_kp==kp && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+integral-before)<3e-7f);
    }
    assert(!motor_td3_g431_response_gain_allowed(.002328243f,.00144f,3800999));
    assert(!motor_td3_g431_response_gain_allowed(.002328243f,.00144f,23101000));
    irq_fault=1;assert(!motor_td3_g431_response_gain_allowed(.002328243f,.00144f,host_us));irq_fault=0;
    motor_td3_g431_disable();assert(test_off());
    }
'''
def run(build,output,compiler):
    oldid=previous.IDENTITY;oldextra=previous.EXTRA;oldlower=lower16.EXTRA
    revised='assert(!motor_td3_g431_response_gain_allowed(nextafterf(.002856927f,-INFINITY),.00144f,host_us));'
    assert previous.EXTRA.count(revised)==1
    try:
        previous.IDENTITY=IDENTITY
        old_reject='assert(!motor_td3_g431_response_gain_allowed(.00285f,.00144f,host_us));'
        assert lower16.EXTRA.count(old_reject)==1
        lower16.EXTRA=lower16.EXTRA.replace(old_reject,old_reject.replace('assert(!','assert('))
        previous.EXTRA=previous.EXTRA.replace(revised,revised.replace('assert(!','assert('))+EXTRA
        r=BASE(build,output,compiler)
    finally:previous.IDENTITY=oldid;previous.EXTRA=oldextra;lower16.EXTRA=oldlower
    r['lower31_v28_checks']=dict(passed=True,retained_v27_checks=True,new_lower_endpoint_and_time_fault_nan_checked=True,
        actual_staged_down_and_restore_commits=16,host_4percent_step_and_bumpless_readback_checked=True,
        adapter_source_sha256=hashlib.sha256((Path(build)/'private-copy/codex-pi/motor_td3_g431_adapter.c').read_bytes()).hexdigest(),hardware_accessed=False,physical_validation=False,deployment_allowed=False)
    (Path(output)/'lower31-v28-summary.json').write_text(json.dumps(r,indent=2)+'\n');return r
if __name__=='__main__':
    p=argparse.ArgumentParser();[p.add_argument('--'+n,required=True) for n in ('build','output','compiler')];a=p.parse_args();run(a.build,a.output,a.compiler)
