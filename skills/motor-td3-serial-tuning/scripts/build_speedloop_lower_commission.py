"""Offline proposal for a separately approved -4% Kp commissioning point.

Never flashes or starts hardware. The new lower point is NOT qualified and
must not be admitted simply because current candidates fail performance.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_interior as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-lower-24s-v15'
V14_PATCH=previous.patch_port


def patch_port(path,motion=False):
    V14_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'if((kp!=0.00345678f && kp!=0.00352456f) || !motion_enabled || irq_fault ||',
        'if((kp!=0.00325344f && kp!=0.00345678f && kp!=0.00352456f) || !motion_enabled || irq_fault ||')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(a):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        report=previous.build(a)
    finally:previous.IDENTITY,previous.patch_port=saved
    report['lower_commission_proposal']=dict(proposed_kp=.00325344,relative_change=-.04,
        baseline_kp=.003389,fixed_ki=.00144,exact_commissioning_kp_levels=[.00325344,.003389,.00345678,.00352456],
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,
        current_speed_bus_duration_lease_limits_modified=False,actor_allowed=False,
        physically_validated=False,operator_approval_required=True,operator_approval_received=False,
        ordinary_policy_gain_envelope_unchanged=True,deployment_allowed=False,
        performance_claim_allowed=False,temperature_gate_modified=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
