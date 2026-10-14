"""Bounded v17 response capture with physical snapshot timestamps and stage proof.

No Actor application or changes to the parameter/trip envelope of v16.
"""
import argparse
import json
from pathlib import Path
import speedloop_ki_response as previous
from speedloop_duration_review import overrides
from build_speedloop_snapshot_review import IDENTITY

IMAGE_SHA='ab87d8defd830872ccb96ed63a7bf34999ec2cc76843d4a50d75ffbc9bf515f0'
HEX_SHA='569ad0347827f4d1ed51ab3a89363d7d9d39daf51095017c0a94cb62d4a18a45'
IMAGE_BYTES=51188
OLD_SHA=previous.IMAGE_SHA
OLD_BYTES=previous.IMAGE_BYTES


def run(args):
    s=json.loads((Path(args.build)/'summary.json').read_text(encoding='utf-8'))
    review=s.get('snapshot_review',{})
    if (not review.get('elapsed_and_timestamp_same_capture')
            or review.get('control_changed') is not False
            or review.get('protection_limits_changed') is not False
            or args.phase=='trial' and not args.stage_journal):
        raise ValueError('Exact timestamp review and per-packet stage journal required')
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   IMAGE_BYTES=IMAGE_BYTES,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
        result=previous.run(args)
    if args.phase=='trial':
        result['timestamp_source']='physical snapshot under interrupt lock'
        result['legacy_timestamp_rewrite']=False
        (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','schedule-contract','stage-journal'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    for name in ('authorized-ki-response','energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file','schedule_contract','stage_journal')}
    if any(not getattr(a,name) for name in needed[a.phase]):p.error('Missing phase paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
