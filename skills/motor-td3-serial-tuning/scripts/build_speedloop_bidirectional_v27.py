"""Offline v27 continuous interpolation within previously measured endpoints."""
import argparse,json
from pathlib import Path
import build_speedloop_upper8_reference_v26 as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-bidirectional-ref-24s-v27'
BASE_PATCH=previous.patch_port
OLD='int kp_probe=(ki==0.00144f && ((kp>0.003389f && kp<=0.00366012f) || kp==0.002856927f || kp==0.003121269f || kp==0.00325344f || kp==0.00345678f || kp==0.00352456f));'
NEW='int kp_probe=(ki==0.00144f && kp>=0.002856927f && kp<=0.00366012f);'

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8');text=replace_once(text,OLD,NEW)
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port;result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    history={}
    for name,record in result.items():
        if isinstance(record,dict) and name.endswith('_review'):
            fields={k:v for k,v in record.items() if 'kp' in k.lower() or 'gain' in k.lower()}
            if fields:
                history[name]=fields
                for k in fields:del record[k]
                record['gain_domain_defined_by']='bidirectional_v27_review'
    result['inherited_gain_review_history']=history
    result['parent_upper8_reference_v26_review']=result.pop('upper8_reference_v26_review')
    result['continuous_review']['fixed_ki']=.00144
    for record in result.values():
        if isinstance(record,dict) and record.get('reference_schedule_defined_by')=='upper8_reference_v26_review':
            record['reference_schedule_defined_by']='bidirectional_v27_review'
    result['bidirectional_v27_review']=dict(response_Kp_domain=[.002856927,.00366012],fixed_Ki=.00144,
        endpoint_scope='Previously measured low -15.7% and high +8%; interpolation not yet physically validated',
        host_single_Kp_step_limit=.00013556,firmware_single_Kp_step_limit=.00027112,
        gain_time_gate_us=[3800000,23100000],reference_levels_rpm=[950,1000,1050],
        active_reference_start_us=6000000,active_reference_end_us=22000000,reference_slot_us=2000000,
        reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,
        FOC_current_loop_PI_commit_and_guard_limits_unchanged=True,
        control_period_changed=False,sensor_filter_changed=False,thermal_gate_modified=False,
        independent_cpu_stall_watchdog_integrated=False,new_bridge_point_requires_bounded_capture=True,
        hardware_accessed=False,flash_programmed=False,physical_validation=False,
        actor_allowed=False,ordinary_deployment_allowed=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','output','arm-bin'):p.add_argument('--'+n,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
