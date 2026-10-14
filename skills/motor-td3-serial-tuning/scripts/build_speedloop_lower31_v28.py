"""Offline v28 experiment proposal; widen Kp lower endpoint without a policy."""
import argparse,json
from pathlib import Path
import build_speedloop_bidirectional_v27 as previous
from build_g431_locked_foc import replace_once
IDENTITY='g431-speedloop-pi-lower31-ref-24s-v28'
BASE_PATCH=previous.patch_port
LOWER=.002328243
def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    t=path.read_text(encoding='utf-8');t=replace_once(t,previous.NEW,'int kp_probe=(ki==0.00144f && kp>=0.002328243f && kp<=0.00366012f);')
    path.write_text(t,encoding='utf-8',newline='\n')
def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:previous.IDENTITY=IDENTITY;previous.patch_port=patch_port;r=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    r['parent_bidirectional_v27_review']=r.pop('bidirectional_v27_review')
    for v in r.values():
        if isinstance(v,dict):
            for k in ('gain_domain_defined_by','reference_schedule_defined_by'):
                if v.get(k)=='bidirectional_v27_review':v[k]='lower31_v28_review'
    r['lower31_v28_review']=dict(response_Kp_domain=[LOWER,.00366012],fixed_Ki=.00144,
        proposed_new_lower_relative_change=-.313,previous_measured_lower_Kp=.002856927,
        proposed_new_staged_points=[.002724756,.002592585,.002460414,LOWER],
        host_single_Kp_step_limit=.00013556,firmware_single_Kp_step_limit=.00027112,
        gain_time_gate_us=[3800000,23100000],reference_levels_rpm=[950,1000,1050],
        active_reference_start_us=6000000,active_reference_end_us=22000000,reference_slot_us=2000000,
        reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],maximum_motion_seconds=24,
        host_stop_seconds=23.8,maximum_commands=480,maximum_batch_rounds=2,maximum_batch_motion_seconds=48,
        minimum_cooldown_seconds=30,FOC_PI_ADC_Hall_timing_reference_and_guard_limits_unchanged=True,
        control_period_changed=False,sensor_filter_changed=False,thermal_gate_modified=False,
        new_points_physically_validated=False,actor_allowed=False,hardware_accessed=False,
        flash_programmed=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(r,indent=2)+'\n');return r
if __name__=='__main__':
    p=argparse.ArgumentParser();[p.add_argument('--'+n,required=True) for n in ('source','output','arm-bin')];p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp');build(p.parse_args())
