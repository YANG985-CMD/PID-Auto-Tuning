"""Offline baseline startup-handover correction with frozen diagnosis trace.

Changes only private generated model startup handover. Original user source,
fixed PI gains, FOC periods, bounds, leases and shutdown stay unchanged.
"""
import argparse,json
from pathlib import Path
import build_speedloop_startup_review as previous
import build_speedloop_pi_integration as original
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-handover-5s-v10'
BASE_COPY=original.patch_copy
BASE_PORT=previous.patch_port

def patch_port(path,motion=False):
    BASE_PORT(path,motion)
    s=path.read_text(encoding='utf-8')
    s=replace_once(s,'#include "motor_td3_trial_timing.h"',
        '#include "motor_td3_trial_timing.h"\n#include "motor_td3_startup_handover.h"')
    s=replace_once(s,'volatile startup_state_record motor_td3_g431_startup_states[128];',
        'volatile startup_state_record motor_td3_g431_startup_states[128];\nvolatile float motor_td3_g431_startup_selected_angles[128];')
    s=replace_once(s,'                motor_td3_g431_startup_state_count=count+1U;',
        '                motor_td3_g431_startup_selected_angles[count]=motor_td3_startup_handover_state.selected_angle;\n'
        '                motor_td3_g431_startup_state_count=count+1U;')
    path.write_text(s,encoding='utf-8',newline='\n')


def patch_copy(copy,can_pi=False,motion=False):
    BASE_COPY(copy,can_pi,motion)
    if not motion:raise ValueError('Explicit reviewed startup motion image required')
    path=copy/'MATLAB/FOC_Model.c';s=path.read_text(encoding='utf-8')
    s=replace_once(s,'#include "motor_td3_speedloop_pi_bind.h"',
        '#include "motor_td3_speedloop_pi_bind.h"\n#include "motor_td3_startup_handover.h"')
    s=replace_once(s,'    rtb_Sum = spd_kpki.spd_kp * rtb_IntegralGain + Integrator;',
        '''    if(rtU.Motor_OnOff==1.0F)
      motor_td3_startup_handover_pi((unsigned)rtDW.Motor_state,
        rtDW.SpeedReset>0.0 && rtDW.Integrator_PrevResetState<=0,
        rtb_IntegralGain,spd_kpki.spd_kp,rtDW.Merge1,&Integrator);
    rtb_Sum = spd_kpki.spd_kp * rtb_IntegralGain + Integrator;''')
    s=replace_once(s,"  /* Trigonometry: '<S2>/SinCos1' */",'''  if(rtU.Motor_OnOff==1.0F)
    ThetaOpen=motor_td3_startup_handover_angle((unsigned)rtDW.Motor_state,ThetaOpen,rtU.theta);
  else motor_td3_startup_handover_reset();
  /* Trigonometry: '<S2>/SinCos1' */''')
    s=replace_once(s,'void FOC_Model_initialize(void)\n{',
        'void FOC_Model_initialize(void)\n{\n  motor_td3_startup_handover_reset();')
    path.write_text(s,encoding='utf-8',newline='\n')


def build(a):
    saved=previous.IDENTITY,original.CAN_FILES,original.patch_copy,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY
        original.CAN_FILES+=('motor_td3_startup_handover.c','motor_td3_startup_handover.h')
        original.patch_copy=patch_copy
        previous.patch_port=patch_port
        report=previous.build(a)
    finally:previous.IDENTITY,original.CAN_FILES,original.patch_copy,previous.patch_port=saved
    report['handover_review']=dict(angle_blend_actual_foc_calls=500,angle_blend_seconds=.05,
        unused_open_pi_integrator_tracking=True,first_run_reset_tracks_previous_iq=True,
        steady_pi_modified=False,fixed_baseline_only=True,control_modified=True,
        protection_limits_modified=False,physical_validation_passed=False,
        actor_allowed=False,ordinary_deployment_allowed=False,performance_claim_allowed=False)
    report['startup_review']['control_modified']=True
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
