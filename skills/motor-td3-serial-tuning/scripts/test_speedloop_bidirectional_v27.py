"""Retained v26 guards plus full-domain real PI commits; no hardware access."""
import argparse,hashlib,json
from pathlib import Path
import test_speedloop_upper8_reference_v26 as previous
import test_speedloop_lower_proposal as target
from build_speedloop_bidirectional_v27 import IDENTITY

EXTRA=r'''
    {
    fresh(101);motion_enabled=1;rtDW.Motor_state=4;
    motor_td3_g431_trial_timing.started=1;motor_td3_g431_trial_timing.started_us=1000;
    motor_td3_g431_trial_timing.run_seen=1;host_us=6501000;
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.002856927f,-INFINITY),.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(nextafterf(.00366012f,INFINITY),.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(-INFINITY,.00144f,host_us));
    assert(!motor_td3_g431_response_gain_allowed(.003f,NAN,host_us));
    assert(motor_td3_begin(&endpoint.guard,host_us,200000));
    float integral=.3f;float stages[]={.00325344f,.003121269f,.002989098f,.002856927f};
    for(unsigned j=0;j<4;j++) {
        float kp=stages[j];uint64_t tick=host_us+1000*j;
        assert(fabsf(kp-spd_kpki.spd_kp)<=.00013556f+1e-9f);
        assert(motor_td3_g431_response_gain_allowed(kp,.00144f,tick));
        assert(motor_td3_apply(&endpoint.guard,tick,j+1,kp,.00144f,200000));
        pi_link.in_boundary=1;pi_link.integral=&integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+integral;
        endpoint.pending.wire_seq=j+1;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,kp,.00144f));
        assert(spd_kpki.spd_kp==kp && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+integral-before)<3e-7f);
    }
    for(unsigned i=0;i<=4000;i++) {
        float ratio=i<=2000?i/2000.f:(4000-i)/2000.f;
        float kp=.002856927f+(.00366012f-.002856927f)*ratio;
        uint64_t tick=host_us+50000+1000*i;
        assert(motor_td3_g431_response_gain_allowed(kp,.00144f,tick));
        assert(!motor_td3_g431_response_gain_allowed(kp,.0014401f,tick));
        if(kp!=.003389f) {
            assert(!motor_td3_g431_response_gain_allowed(kp,.00144f,3800999));
            assert(!motor_td3_g431_response_gain_allowed(kp,.00144f,23101000));
        }
        endpoint.guard.commands=0; /* Test only; retained production budget tests remain. */
        assert(motor_td3_apply(&endpoint.guard,tick,i+10,kp,.00144f,200000));
        pi_link.in_boundary=1;pi_link.integral=&integral;pi_link.now_us=tick;
        pi_link.error=125;pi_link.reset=pi_link.applied=0;
        float before=spd_kpki.spd_kp*125+integral;
        endpoint.pending.wire_seq=i+10;endpoint.pending.command.lease_ms=200;
        assert(endpoint.hooks.apply(endpoint.hooks.user,kp,.00144f));
        assert(spd_kpki.spd_kp==kp && spd_kpki.spd_ki==.00144f);
        assert(fabsf(spd_kpki.spd_kp*125+integral-before)<3e-7f);
    }
    irq_fault=1;assert(!motor_td3_g431_response_gain_allowed(.003f,.00144f,host_us));
    irq_fault=0;motor_td3_g431_trial_timing.fault=1;
    assert(!motor_td3_g431_response_gain_allowed(.003f,.00144f,host_us));
    motor_td3_g431_trial_timing.fault=0;rtDW.Motor_state=3;
    assert(!motor_td3_g431_response_gain_allowed(.003f,.00144f,host_us));
    motor_td3_g431_disable();assert(test_off());
    }
'''

def run(build,output,compiler):
    build,output=map(Path,(build,output));assert json.loads((build/'summary.json').read_text())['build_id']==IDENTITY
    original=target.BASE_RUN;saved_id=previous.IDENTITY
    def checked(b,o,c,duration_review=False,harness=None):
        revised=[]
        for gain,clock in (('.0032f','6501000'),('.00311788f','6501000'),('nextafterf(.003389f,-INFINITY)','host_us')):
            old=f'assert(!motor_td3_g431_response_gain_allowed({gain},.00144f,{clock}));'
            if harness.count(old)!=1:raise ValueError('Exact old discrete-domain rejection fixture missing')
            harness=harness.replace(old,old.replace('assert(!','assert('));revised.append(old)
        marker='    puts("{\\"passed\\":true';assert harness.count(marker)==1
        result=original(b,o,c,duration_review=duration_review,harness=harness.replace(marker,EXTRA+marker))
        result['revised_continuous_negative_acceptance_fixtures']=revised;return result
    try:
        previous.IDENTITY=IDENTITY;target.BASE_RUN=checked;result=previous.run(build,output,compiler)
    finally:previous.IDENTITY=saved_id;target.BASE_RUN=original
    result['bidirectional_v27_checks']=dict(passed=True,retained_v26_upper_PI_commits=2001,
        full_domain_continuous_PI_commits=4001,negative_bridge_PI_commits=4,
        all_old_stop_lease_guard_and_reference_checks_retained=True,
        exact_float32_application_and_bumpless_PI_checked=True,
        lower_upper_ULP_NaN_Ki_time_fault_stage_boundaries_checked=True,
        adapter_source_sha256=hashlib.sha256((build/'private-copy/codex-pi/motor_td3_g431_adapter.c').read_bytes()).hexdigest(),
        hardware_accessed=False,physical_validation=False,deployment_allowed=False)
    (output/'bidirectional-v27-summary.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','output','compiler'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
