"""Offline v23 small exogenous reference steps; v22 FOC/gains/guards retained."""
import argparse
import json
from pathlib import Path
import build_speedloop_sampling_v22 as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-reference-24s-v23'
BASE_PATCH=previous.patch_port


def reference_rpm(elapsed_us):
    if elapsed_us<6000000 or elapsed_us>=22000000:return 1000.
    return (1000.,950.,1000.,1050.)[int((elapsed_us-6000000)//2000000)%4]


def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,
        '''    (void)elapsed;
    return 1000.0f; /* Constant exogenous reference for action attribution. */''',
        '''    /* Exogenous +/-50 rpm steps. Keep startup/finish at baseline.
     * Bounds precede the 32-bit subtraction; no heap or stateful scheduler. */
    if(elapsed<6000000ULL || elapsed>=22000000ULL) return 1000.0f;
    uint32_t phase=(uint32_t)(elapsed-6000000ULL)/2000000U;
    static const float refs[4]={1000.0f,950.0f,1000.0f,1050.0f};
    return refs[phase%4U];''')
    path.write_text(text,encoding='utf-8',newline='\n')


def apply_reference_metadata(result):
    history={}
    for key in ('response_review','excitation_review','continuous_review','fixedref_review','lower16_review'):
        record=result.get(key,{})
        history[key]={k:v for k,v in record.items() if 'ref' in k}
    result['parent_reference_review_history']=history
    result['response_review'].pop('speed_ref_rpm',None)
    result['response_review']['initial_speed_ref_rpm']=1000
    result['excitation_review'].update(reference_schedule_ms_rpm=[[0,1000],[6000,1000],[8000,950],
        [10000,1000],[12000,1050],[14000,1000],[16000,950],[18000,1000],[20000,1050],[22000,1000]],
        minimum_reference_rpm=950,maximum_reference_rpm=1050)
    result['continuous_review'].update(reference_cycle_start_ms=6000,reference_cycle_ms=8000,
        reference_cycle_rpm=[1000,950,1000,1050],reference_final_baseline_ms=22000)
    for key in ('fixedref_review','lower16_review'):
        result[key].pop('reference_rpm',None)
        result[key]['initial_reference_rpm']=1000
        result[key]['reference_schedule_constant']=False
    result['sampling_v22_review'].pop('reference_rpm',None)
    result['sampling_v22_review']['initial_reference_rpm']=1000
    result['sampling_v22_review']['reference_schedule_constant']=False
    result['reference_v23_review']=dict(reference_levels_rpm=[950,1000,1050],
        initial_and_finish_reference_rpm=1000,active_reference_start_us=6000000,
        active_reference_end_us=22000000,reference_slot_us=2000000,
        reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
        exogenous_reference_independent_of_gains_and_rewards=True,
        original_foc_pi_gain_application_unchanged=True,sensor_filter_changed=False,
        control_period_changed=False,protection_limits_changed=False,
        gain_allowlist_changed=False,thermal_gate_modified=False,
        maximum_motion_seconds=24,host_stop_seconds=23.8,
        actor_allowed=False,deployment_allowed=False,performance_claim_allowed=False,
        new_capture_and_reward_profile_required=True)
    return result


def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    apply_reference_metadata(result)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
