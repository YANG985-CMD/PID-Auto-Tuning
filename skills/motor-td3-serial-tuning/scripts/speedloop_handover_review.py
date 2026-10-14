"""Single fixed-PI 5s v10 handover trial. No Actor, no parameter exploration."""
import argparse,hashlib,json
from pathlib import Path
import speedloop_startup_review as previous
from speedloop_duration_review import overrides
from build_speedloop_handover_review import IDENTITY

IMAGE_SHA='7f1bcbcb27515a0eb2ebcbd8cd6b6a0f2f1390a557be29082adc3730b39a6562'
HEX_SHA='88f02f0bdedf0d7845ca8e8abc53b11b21120bed4bc1efc73a7a6c98c749de59'
OLD_SHA=previous.IMAGE_SHA
OLD_BYTES=50496
IMAGE_BYTES=51112

def run(a):
    if not getattr(a,'authorized_handover_review',False):raise ValueError('Single bounded handover scope required')
    info=json.loads((Path(a.build)/'summary.json').read_text(encoding='utf-8'))
    h=info.get('handover_review',{})
    if (info['build_id']!=IDENTITY or not h.get('fixed_baseline_only') or
        h.get('angle_blend_actual_foc_calls')!=500 or h.get('steady_pi_modified') is not False or
        h.get('protection_limits_modified') is not False):raise ValueError('Unexpected handover control contract')
    a.authorized_startup_review=True
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,IMAGE_BYTES=IMAGE_BYTES):
        result=previous.run(a)
    if a.phase=='trial':
        result.update(runtime_profile='single-5s-baseline-handover-v1',handover_control_modified=True,
            runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-handover-review',action='store_true')
    p.add_argument('--gain-mode',default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed','energized-phase-inhibited-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in required[a.phase]):p.error('Missing phase-specific paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
