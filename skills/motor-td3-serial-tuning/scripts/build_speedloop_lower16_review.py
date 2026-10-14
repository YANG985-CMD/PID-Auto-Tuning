"""Private v21 exact -15.7% Kp commissioning point; existing limits retained."""
import argparse
import json
from pathlib import Path
import build_speedloop_fixedref_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-lower16-24s-v21'
BASE_PATCH=previous.patch_port
NEW_KP=.002856927

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,
        'int kp_probe=(ki==0.00144f && (kp==0.003121269f ||',
        'int kp_probe=(ki==0.00144f && (kp==0.002856927f || kp==0.003121269f ||')
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['lower16_review']=dict(exact_kp_levels=[.003389,.003121269,NEW_KP],
        fixed_ki=.00144,new_point_relative_change=-.157,required_bridge_kp=.003121269,
        maximum_single_command_kp_change=.00027112,maximum_motion_seconds=24,
        host_stop_seconds=23.8,maximum_commands=480,reference_rpm=1000,
        current_speed_bus_duration_lease_limits_modified=False,actor_allowed=False,
        thermal_gate_modified=False,deployment_allowed=False,performance_claim_allowed=False,
        human_authorization_source='Direct human authorization to explore larger Kp/Ki ranges')
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
