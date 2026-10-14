"""Reviewed v25 continuous upper Kp response domain; capture only, no Actor."""
import argparse
import json
from pathlib import Path
import build_speedloop_upper8_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-upper8-cont-24s-v25'
BASE_PATCH=previous.patch_port

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,
        'int kp_probe=(ki==0.00144f && (kp==0.00366012f ||',
        'int kp_probe=(ki==0.00144f && ((kp>0.003389f && kp<=0.00366012f) ||')
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['continuous_upper8_review']=dict(
        firmware_response_kp_domain=[.003389,.00366012],fixed_ki=.00144,
        response_domain_semantics='float32 absolute Kp; baseline restoration retains old semantics',
        firmware_single_kp_step_limit=.00027112,host_single_kp_step_limit=.00013556,
        response_time_gate_ms=[3800,23100],reference_rpm=1000,
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,
        general_parameter_and_physical_limits_changed=False,control_period_changed=False,
        sensor_filter_changed=False,thermal_gate_modified=False,
        continuous_domain_is_physically_validated=False,
        independent_cpu_stall_watchdog_integrated=False,actor_allowed=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
