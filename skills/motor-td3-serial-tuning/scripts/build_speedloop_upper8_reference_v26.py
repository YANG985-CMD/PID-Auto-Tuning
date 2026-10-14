"""Offline v26: reviewed v25 PI domain with the existing small reference steps.

This builder changes only the adapter's predetermined reference schedule. It
does not connect an Actor or modify FOC, PI commits, stop rules or protection.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_upper8_continuous as previous
from build_g431_locked_foc import replace_once
from build_speedloop_reference_v23 import reference_rpm

IDENTITY='g431-speedloop-pi-upper8-ref-24s-v26'
BASE_PATCH=previous.patch_port
ACTIVE_REFERENCE_BODY='''    /* Fixed exogenous schedule previously used in v23. Bounds before narrowing. */
    if(elapsed<6000000ULL || elapsed>=22000000ULL) return 1000.0f;
    uint32_t phase=(uint32_t)(elapsed-6000000ULL)/2000000U;
    static const float refs[4]={1000.0f,950.0f,1000.0f,1050.0f};
    return refs[phase%4U];'''

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'''    (void)elapsed;
    return 1000.0f; /* Constant exogenous reference for action attribution. */''',ACTIVE_REFERENCE_BODY)
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    # Remove stale constant/reference assertions from inherited metadata;
    # keep their history explicitly scoped to the prior build.
    history={}
    for name,record in result.items():
        if isinstance(record,dict) and name.endswith('_review'):
            changed={k:record[k] for k in tuple(record) if 'ref' in k.lower()}
            if changed:
                history[name]=changed
                for k in changed:del record[k]
                record['reference_schedule_defined_by']='upper8_reference_v26_review'
    result['inherited_reference_review_history']=history
    result['upper8_reference_v26_review']=dict(reference_levels_rpm=[950,1000,1050],
        initial_and_finish_reference_rpm=1000,active_reference_start_us=6000000,
        active_reference_end_us=22000000,reference_slot_us=2000000,
        reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
        exogenous_reference_independent_of_actions_and_rewards=True,
        Kp_response_domain=[.003389,.00366012],fixed_Ki=.00144,
        host_single_Kp_step_limit=.00013556,firmware_single_Kp_step_limit=.00027112,
        gain_time_gate_us=[3800000,23100000],maximum_motion_seconds=24,host_stop_seconds=23.8,
        FOC_and_current_loop_and_PI_boundary_unchanged=True,parameter_limits_unchanged=True,
        control_period_changed=False,sensor_filter_changed=False,protection_limits_changed=False,
        thermal_gate_modified=False,independent_cpu_stall_watchdog_integrated=False,
        ordinary_deployment_allowed=False,actor_allowed=False,
        new_capture_reward_and_action_contract_required=True,
        hardware_accessed=False,physical_validation=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
