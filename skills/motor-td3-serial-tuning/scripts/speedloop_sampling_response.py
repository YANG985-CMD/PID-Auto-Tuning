"""One finite v18 Ki response trial with deterministic collection dither."""
import argparse
import json
from pathlib import Path
import speedloop_snapshot_response as previous
from speedloop_duration_review import overrides
from build_speedloop_sampling_review import IDENTITY

IMAGE_SHA='235469c41e853e16d973cfdca315ba583ce6075281f7c3ed4b7aeddee2327af9'
HEX_SHA='db7c64b319b0300409d964826c88c1983527d4e96c0e7098153f4005348066b3'
IMAGE_BYTES=51216
OLD_SHA=previous.IMAGE_SHA
OLD_BYTES=previous.IMAGE_BYTES


def run(args):
    info=json.loads((Path(args.build)/'summary.json').read_text(encoding='utf-8'))
    review=info.get('sampling_review',{})
    if (review.get('interval_rule')!='18500+(telemetry_seq*997)%3001 microseconds'
            or review.get('sensor_filter_changed') is not False
            or review.get('control_period_changed') is not False
            or review.get('protection_limits_changed') is not False):
        raise ValueError('Exact collection-only sampling contract required')
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   IMAGE_BYTES=IMAGE_BYTES,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
        result=previous.run(args)
    if args.phase=='trial':
        result['collection_sampling_dither']=review
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
