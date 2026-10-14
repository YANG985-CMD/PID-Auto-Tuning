"""Exact +8% Kp capture point; fixed 1000 rpm and all v22 guards retained."""
import argparse
import json
from pathlib import Path
import build_speedloop_sampling_v22 as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-upper8-24s-v24'
BASE_PATCH=previous.patch_port

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,
        'int kp_probe=(ki==0.00144f && (kp==0.002856927f ||',
        'int kp_probe=(ki==0.00144f && (kp==0.00366012f || kp==0.002856927f ||')
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['upper8_review']=dict(exact_kp_levels=[.003389,.00352456,.00366012],
        fixed_ki=.00144,reference_rpm=1000,new_point_relative_change=.08,
        required_bridge_kp=.00352456,host_single_kp_step_limit=.00013556,
        firmware_single_kp_step_limit=.00027112,maximum_motion_seconds=24,
        host_stop_seconds=23.8,maximum_commands=480,
        general_parameter_and_physical_limits_changed=False,
        response_allowlist_new_point=.00366012,
        control_period_changed=False,sensor_filter_changed=False,
        thermal_gate_modified=False,actor_allowed=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
