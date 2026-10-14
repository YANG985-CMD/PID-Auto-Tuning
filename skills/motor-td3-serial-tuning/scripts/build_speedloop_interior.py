"""Offline v14 fixed +2% commissioning point inside unchanged gain endpoints.

No Actor integration. All current/speed/bus/duration/lease limits stay v13.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_continuous as previous
import build_speedloop_excitation_review as excitation
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-interior-24s-v14'
V13_PATCH=previous.patch_port


def patch_port(path,motion=False):
    V13_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'if(kp!=0.00352456f || !motion_enabled || irq_fault ||',
        'if((kp!=0.00345678f && kp!=0.00352456f) || !motion_enabled || irq_fault ||')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(a):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        report=previous.build(a)
    finally:previous.IDENTITY,previous.patch_port=saved
    report['interior_review']=dict(exact_kp_levels=[.003389,.00345678,.00352456],
        normalized_absolute_targets=[0,.25,.5],fixed_ki=.00144,
        lower_gain_endpoint_unchanged=True,upper_gain_endpoint_unchanged=True,
        current_speed_bus_duration_lease_limits_modified=False,actor_allowed=False,
        new_midpoint_physically_validated=False,deployment_allowed=False,
        performance_claim_allowed=False,temperature_gate_modified=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
