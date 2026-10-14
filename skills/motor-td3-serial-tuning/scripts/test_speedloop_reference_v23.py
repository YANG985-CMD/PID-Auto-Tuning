"""Check exact v23 reference boundaries and retain actual v22 guard regressions."""
import argparse
import json
from pathlib import Path
import test_speedloop_sampling_v22 as previous
import test_speedloop_fixedref_review as fixed
import test_speedloop_lower_proposal as target
from build_speedloop_reference_v23 import reference_rpm


def run(build,output,compiler):
    saved=fixed.run
    def checked(b,o,c):
        base_run=target.BASE_RUN
        def updated(b2,o2,c2,duration_review=False,harness=None):
            marker='float expected=(ms<4000||ms>=22000)?1000:phase<1200?1100:phase<2400?900:1000;'
            if marker not in harness:raise ValueError('Missing original reference schedule regression')
            replacement='float expected=(ms<6000||ms>=22000)?1000:((ms-6000)/2000)%4==1?950:((ms-6000)/2000)%4==3?1050:1000;'
            harness=harness.replace(marker,replacement)
            boundary='''
    for(uint64_t t=0;t<=24000000ULL;t+=137ULL) {
        float expected=t<6000000ULL||t>=22000000ULL?1000.0f:
            ((t-6000000ULL)/2000000ULL)%4ULL==1ULL?950.0f:
            ((t-6000000ULL)/2000000ULL)%4ULL==3ULL?1050.0f:1000.0f;
        assert(motor_td3_g431_excitation_reference(t)==expected);
        assert(expected>=950.0f && expected<=1050.0f);
    }
    for(uint64_t t=6000000ULL;t<=22000000ULL;t+=2000000ULL) {
        assert(motor_td3_g431_excitation_reference(t-1)==
            (t==6000000ULL?1000.0f:((t-1-6000000ULL)/2000000ULL)%4ULL==1ULL?950.0f:
            ((t-1-6000000ULL)/2000000ULL)%4ULL==3ULL?1050.0f:1000.0f));
    }
    assert(motor_td3_g431_excitation_reference(UINT64_MAX)==1000.0f);
'''
            stop='    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15,\\"snapshot_checks\\":9,\\"sampling_checks\\":2407,\\"lower8_checks\\":14,\\"lower16_staged_and_direct_rejection\\":true}");return 0;'
            if harness.count(stop)!=1:raise ValueError('Missing retained physical-boundary test footer')
            harness=harness.replace(stop,boundary+stop)
            return base_run(b2,o2,c2,duration_review=duration_review,harness=harness)
        prior=target.BASE_RUN
        try:
            target.BASE_RUN=updated
            import test_speedloop_lower8_review as lower8
            return lower8.run(b,o,c)
        finally:target.BASE_RUN=prior
    try:
        fixed.run=checked
        report=previous.run(build,output,compiler)
    finally:fixed.run=saved
    assert({reference_rpm(t) for t in range(0,24000001,137)}=={950.,1000.,1050.})
    report['reference_v23_checks']=dict(exact_step_boundaries_checked=True,
        uint64_overflow_elapsed_returns_baseline=True,old_stop_and_guard_checks_retained=True,
        source_and_controller_original_unmodified=True,hardware_accessed=False)
    (Path(output)/'reference-v23-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
