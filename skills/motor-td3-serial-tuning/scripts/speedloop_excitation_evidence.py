"""Exact v12 image, bounded baseline/+4% Kp, no Actor or Ki change."""
import argparse
import json
from pathlib import Path
import speedloop_handover_excitation as previous
import speedloop_excitation_review as excitation
from speedloop_duration_review import overrides
from build_speedloop_excitation_evidence import IDENTITY, CAPACITY

IMAGE_SHA='f1e48e4033a7c3fd4cf645b9050c157325ed507580f7f3d60e5b573a0620dd4a'
HEX_SHA='f505419cdf1e6636eb3914e7a927cbe663a5b47e0d901bc92dec0e0d26a68a98'
IMAGE_BYTES=51084
OLD_SHA='d97d6cc58d24d5b30ff5d6644d63ab673a56c461d82e4e051ea7f68f80a58413'
OLD_BYTES=51080


def validate(a):
    if not getattr(a,'authorized_excitation_evidence',False):
        raise ValueError('Bounded evidence experiment scope required')
    info=json.loads((Path(a.build)/'summary.json').read_text(encoding='utf-8'))
    e=info.get('evidence_review',{})
    if (info['build_id']!=IDENTITY or e.get('control_modified') is not False or
        e.get('limits_modified') is not False or e.get('stack_reserve_bytes',0)<4096 or
        info.get('hall_trace_capacity')!=CAPACITY):
        raise ValueError('Unexpected evidence-only image contract')
    a.authorized_excitation_review=True
    with overrides(excitation, IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   IMAGE_BYTES=IMAGE_BYTES,HALL_TRACE_CAPACITY=CAPACITY):
        return excitation.validate(a)


def run(a):
    validate(a) # Authorization, identity, hashes and action gate before hardware.
    a.authorized_handover_excitation=True
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   IMAGE_BYTES=IMAGE_BYTES,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES), \
         overrides(excitation,HALL_TRACE_CAPACITY=CAPACITY):
        result=previous.run(a)
    if a.phase=='trial':
        result.update(runtime_profile='8s-excitation-evidence-v1',
            hall_trace_capacity=CAPACITY,control_equivalent_to=previous.IDENTITY,
            ordinary_deployment_allowed=False,performance_claim_allowed=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-excitation-evidence',action='store_true')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    required={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in required[a.phase]):p.error('Missing phase paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
