"""Exact v11 bounded reference data trial. No Actor or Ki exploration."""
import argparse,json,hashlib
from pathlib import Path
import speedloop_excitation_review as previous
from speedloop_duration_review import overrides
from build_speedloop_handover_excitation import IDENTITY

IMAGE_SHA='d97d6cc58d24d5b30ff5d6644d63ab673a56c461d82e4e051ea7f68f80a58413'
HEX_SHA='fce2284799e3e9934a836c5f6559d592b64977bdb0787999583584091c189b9b'
OLD_SHA='7f1bcbcb27515a0eb2ebcbd8cd6b6a0f2f1390a557be29082adc3730b39a6562'
OLD_BYTES=51112
IMAGE_BYTES=51080

def run(a):
    if not getattr(a,'authorized_handover_excitation',False):raise ValueError('Bounded handover excitation scope required')
    info=json.loads((Path(a.build)/'summary.json').read_text(encoding='utf-8'))
    h=info.get('handover_review',{})
    if (info['build_id']!=IDENTITY or h.get('actor_allowed') is not False or
        h.get('angle_blend_actual_foc_calls')!=500 or h.get('steady_pi_modified') is not False or
        h.get('protection_limits_modified') is not False):raise ValueError('Unexpected handover excitation contract')
    a.authorized_excitation_review=True
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,
                   OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,IMAGE_BYTES=IMAGE_BYTES):
        result=previous.run(a)
    if a.phase=='trial':
        result.update(runtime_profile='two-round-8s-handover-excitation-v1',handover_control_modified=True,
            runtime_profile_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-handover-excitation',action='store_true')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed','energized-phase-inhibited-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in required[a.phase]):p.error('Missing phase-specific paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
