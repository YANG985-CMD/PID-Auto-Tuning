"""Offline proposal: exact Ki -9.9/-19.7% points, no new physical validation."""
import argparse
import json
from pathlib import Path
import build_speedloop_sampling_v22 as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-ki20-24s-v23'
BASE_PATCH=previous.patch_port
KI_BRIDGE=.00129744
KI_LOW=.00115632

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'int ki_probe=(kp==0.003389f && (ki==0.001404f || ki==0.001476f));',
        'int ki_probe=(kp==0.003389f && (ki==0.00115632f || ki==0.00129744f || ki==0.001404f || ki==0.001476f));')
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['ki20_proposal']=dict(exact_ki_levels=[.00144,KI_BRIDGE,KI_LOW],fixed_kp=.003389,
        maximum_single_command_ki_change=.000144,requires_actual_bridge_readback=True,
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,
        user_larger_parameter_exploration_authorized=True,physically_validated=False,
        network_ki_mask_changed=False,current_speed_bus_duration_lease_limits_modified=False,
        thermal_gate_modified=False,actor_allowed=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','output','arm-bin'):p.add_argument('--'+n,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
