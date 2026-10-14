"""Private v20 fixed1000rpm action-support capture, using v19 gains/limits.

Only the predefined reference schedule is replaced. No Actor or range change.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_lower8_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-fixedref-24s-v20'
BASE_PATCH=previous.patch_port


def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'''    if(elapsed<4000000ULL || elapsed>=22000000ULL) return 1000.0f;
    uint64_t phase=(elapsed-4000000ULL)%3600000ULL;
    return phase<1200000ULL?1100.0f:phase<2400000ULL?900.0f:1000.0f;''',
        '''    (void)elapsed;
    return 1000.0f; /* Constant exogenous reference for action attribution. */''')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['fixedref_review']=dict(reference_rpm=1000,reference_schedule_changed=True,
        original_foc_pi_and_gain_application_unchanged=True,exact_kp_levels=[.003389,.00325344,.003121269],
        fixed_ki=.00144,maximum_motion_seconds=24,host_stop_seconds=23.8,
        current_speed_bus_duration_lease_limits_modified=False,actor_allowed=False,
        thermal_gate_modified=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
