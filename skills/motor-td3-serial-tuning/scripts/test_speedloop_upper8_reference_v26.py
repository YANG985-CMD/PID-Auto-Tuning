"""Check actual v26 reference schedule, retain all v25 PI and stop checks."""
import argparse
import hashlib
import json
from pathlib import Path
import test_speedloop_upper8_continuous_review as previous
import test_speedloop_lower_proposal as target
from build_speedloop_upper8_reference_v26 import reference_rpm,IDENTITY

EXTRA=r'''
    for(uint64_t t=0;t<=24000000ULL;t+=137ULL) {
        float expected=t<6000000ULL||t>=22000000ULL?1000.0f:
            ((t-6000000ULL)/2000000ULL)%4ULL==1ULL?950.0f:
            ((t-6000000ULL)/2000000ULL)%4ULL==3ULL?1050.0f:1000.0f;
        assert(motor_td3_g431_excitation_reference(t)==expected);
    }
    for(uint64_t boundary=6000000ULL;boundary<=22000000ULL;boundary+=2000000ULL) {
        for(int offset=-2;offset<=2;offset++) {
            uint64_t t=(uint64_t)((int64_t)boundary+offset);
            float expected=t<6000000ULL||t>=22000000ULL?1000.0f:
                ((t-6000000ULL)/2000000ULL)%4ULL==1ULL?950.0f:
                ((t-6000000ULL)/2000000ULL)%4ULL==3ULL?1050.0f:1000.0f;
            assert(motor_td3_g431_excitation_reference(t)==expected);
        }
    }
    assert(motor_td3_g431_excitation_reference(UINT64_MAX)==1000.0f);
    assert(motor_td3_g431_excitation_reference(0x100000000ULL)==1000.0f);
'''

def run(build,output,compiler):
    build,output=Path(build),Path(output)
    assert json.loads((build/'summary.json').read_text())['build_id']==IDENTITY
    original=target.BASE_RUN
    def checked(b,o,c,duration_review=False,harness=None):
        marker='float expected=1000; (void)phase;'
        if harness.count(marker)!=1:raise ValueError('Constant-reference inherited test missing')
        harness=harness.replace(marker,
            'float expected=(ms<6000||ms>=22000)?1000:((ms-6000)/2000)%4==1?950:((ms-6000)/2000)%4==3?1050:1000; (void)phase;')
        footer='    puts("{\\"passed\\":true'
        if harness.count(footer)!=1:raise ValueError('Retained test footer missing')
        return original(b,o,c,duration_review=duration_review,harness=harness.replace(footer,EXTRA+footer))
    try:
        target.BASE_RUN=checked
        result=previous.run(build,output,compiler)
    finally:target.BASE_RUN=original
    assert {reference_rpm(t) for t in range(0,24000001,137)}=={950.,1000.,1050.}
    result['upper8_reference_v26_checks']=dict(passed=True,reference_samples=175183,
        exact_reference_boundary_checks=45,uint64_overflow_baseline_checked=True,
        all_v25_continuous_PI_commits_and_guards_retained=True,
        v25_stop_lease_and_protocol_regressions_retained=True,hardware_accessed=False,
        adapter_source_sha256=hashlib.sha256((build/'private-copy/codex-pi/motor_td3_g431_adapter.c').read_bytes()).hexdigest(),
        physical_validation=False,deployment_allowed=False)
    (output/'reference-v26-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
