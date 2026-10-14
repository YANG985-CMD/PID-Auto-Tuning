"""Stopped exact v24 Hall-read qualification, same 6ms deadline."""
import argparse
import benchmark_speedloop_v23_reads as previous
from speedloop_duration_review import overrides
from speedloop_upper8_probe import IMAGE_SHA,IMAGE_BYTES,IDENTITY

def run(a):
    with overrides(previous,IMAGE_SHA=IMAGE_SHA,IMAGE_BYTES=IMAGE_BYTES,IDENTITY=IDENTITY):
        return previous.run(a)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841');a=p.parse_args()
    raise SystemExit(0 if run(a)['passed'] else 1)
