"""Finite reactive/baseline pair. Existing exact-image stop gates stay in force."""
import argparse
import collect_speedloop_response as collector
import speedloop_reactive_probe as review
from speedloop_duration_review import overrides


def run(a):
    with overrides(collector,review=review,REVIEW_SCRIPT='speedloop_reactive_probe.py',
                   SCOPE_FLAG='--authorized-reactive-probe',COLLECTION_SOURCE='reactive_two_gain_experience'):
        return collector.run(a)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-reactive-probe','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    p.add_argument('--order',choices=('baseline-first','probe-first'),default='baseline-first')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
