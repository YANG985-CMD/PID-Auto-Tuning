"""Test actual v18 collection timing plus previous stop/gain regressions."""
import argparse
import test_speedloop_snapshot_review as previous

EXTRA=r'''
    uint64_t sample_time=0,interval_sum=0;unsigned sampled_sectors[6]={0};
    for(unsigned seq=1;seq<=1200;seq++) {
        uint32_t dt=motor_td3_g431_diag_interval_us(seq);
        assert(dt==18500U+((uint64_t)seq*997U)%3001U);
        assert(dt>=18500U && dt<=21500U);
        sample_time+=dt;interval_sum+=dt;sampled_sectors[(sample_time/5000)%6]++;
    }
    for(unsigned i=0;i<6;i++) assert(sampled_sectors[i]>150 && sampled_sectors[i]<260);
    assert(interval_sum==23999400ULL);
    motor_td3_g431_disable();assert(test_off());
    puts("{\"passed\":true,\"original_lower_regressions_retained\":true,\"ki_checks\":15,\"snapshot_checks\":9,\"sampling_checks\":2407}");return 0;
'''


def run(build,output,compiler):
    prior=previous.EXTRA
    marker='    puts("{\\"passed\\":true,\\"original_lower_regressions_retained\\":true,\\"ki_checks\\":15,\\"snapshot_checks\\":9}");return 0;'
    assert prior.count(marker)==1
    try:
        previous.EXTRA=prior.replace(marker,EXTRA)
        return previous.run(build,output,compiler)
    finally:previous.EXTRA=prior


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
