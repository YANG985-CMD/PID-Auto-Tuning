"""Offline v11 combines v8 bounded references with tested v10 handover.

Keeps the late Hall ring; frozen commissioning arrays are excluded for SRAM.
Only baseline/+4% Kp and fixed Ki, never an Actor image.
"""
import argparse,json
from pathlib import Path
import build_speedloop_excitation_review as excitation
import build_speedloop_pi_integration as original
from build_speedloop_handover_review import patch_copy

IDENTITY='g431-speedloop-pi-handover-excitation-8s-v11'

def build(a):
    saved=excitation.IDENTITY,original.CAN_FILES,original.patch_copy
    try:
        excitation.IDENTITY=IDENTITY
        original.CAN_FILES+=('motor_td3_startup_handover.c','motor_td3_startup_handover.h')
        original.patch_copy=patch_copy
        report=excitation.build(a)
    finally:excitation.IDENTITY,original.CAN_FILES,original.patch_copy=saved
    report['handover_review']=dict(angle_blend_actual_foc_calls=500,angle_blend_seconds=.05,
        unused_open_pi_integrator_tracking=True,first_run_reset_tracks_previous_iq=True,
        steady_pi_modified=False,fixed_ki=.00144,control_modified=True,
        protection_limits_modified=False,actor_allowed=False,physical_validation_passed=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False)
    report['commissioning_basis']='v10 single fixed-baseline run; not repeated startup stability evidence'
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
