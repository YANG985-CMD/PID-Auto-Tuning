"""One v8 reference-excitation pair; 2x8s reserved, 30s cooldown, fault abort."""
import argparse
import collect_speedloop_response as collector
import speedloop_excitation_review as review


def run(args):
    with review.overrides(collector,review=review,REVIEW_SCRIPT='speedloop_excitation_review.py',
            SCOPE_FLAG='--authorized-excitation-review',COLLECTION_SOURCE='real_motor_excitation_review'):
        return collector.run(args)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-excitation-review','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    p.add_argument('--order',choices=('baseline-first','probe-first'),default='baseline-first')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
