"""Actual v20 adapter/regression checks on host, no hardware."""
import argparse
import test_speedloop_lower8_review as previous
import test_speedloop_lower_proposal as target


def run(build,output,compiler):
    # The earlier 24s harness adds its schedule assertion after HARNESS.
    base_run=target.BASE_RUN
    def checked(b,o,c,duration_review=False,harness=None):
        old='float expected=(ms<4000||ms>=22000)?1000:phase<1200?1100:phase<2400?900:1000;'
        if old not in harness:raise ValueError('Expected original reference regression missing')
        harness=harness.replace(old,'float expected=1000; (void)phase;')
        return base_run(b,o,c,duration_review=duration_review,harness=harness)
    saved=target.BASE_RUN
    try:
        target.BASE_RUN=checked
        return previous.run(build,output,compiler)
    finally:
        target.BASE_RUN=saved


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
