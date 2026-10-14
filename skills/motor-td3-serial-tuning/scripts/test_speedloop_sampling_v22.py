"""v22 cadence parity/bounds/coverage plus all v21 model regressions."""
import argparse
import test_speedloop_sampling_review as sampling
import test_speedloop_lower16_review as previous
from build_speedloop_sampling_v22 import interval_us

def run(build,output,compiler):
    prior=sampling.EXTRA;values=[interval_us(i) for i in range(1,1201)]
    new=prior.replace('uint64_t sample_time=0,interval_sum=0;',
        'static const uint32_t cadence_reference[1200]={'+','.join(map(str,values))+'};\n    uint64_t sample_time=0,interval_sum=0;')
    new=new.replace('assert(dt==18500U+((uint64_t)seq*997U)%3001U);',
        'assert(dt==cadence_reference[seq-1]);')
    new=new.replace('assert(interval_sum==23999400ULL);',f'assert(interval_sum=={sum(values)}ULL);')
    assert new!=prior and '23999400' not in new
    try:
        sampling.EXTRA=new
        return previous.run(build,output,compiler)
    finally:sampling.EXTRA=prior

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','output','compiler'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
