"""Offline warm-loop Ki +/-2.5% review, using previously measured points.

This extends response observation, not the current/speed/bus/lease limits.
No Actor, no hardware access, no ordinary deployment qualification.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_lower_commission as previous
from build_g431_locked_foc import replace_once

IDENTITY = 'g431-speedloop-pi-ki-24s-v16'
BASE_PATCH = previous.patch_port


def patch_port(path, motion=False):
    BASE_PATCH(path, motion)
    text = path.read_text(encoding='utf-8')
    old = '''    if(ki!=0.00144f) return 0;
    if(kp==0.003389f) return 1;
    if((kp!=0.00325344f && kp!=0.00345678f && kp!=0.00352456f) || !motion_enabled || irq_fault ||'''
    new = '''    if(kp==0.003389f && ki==0.00144f) return 1;
    int ki_probe=(kp==0.003389f && (ki==0.001404f || ki==0.001476f));
    int kp_probe=(ki==0.00144f && (kp==0.00325344f || kp==0.00345678f || kp==0.00352456f));
    if((!ki_probe && !kp_probe) || !motion_enabled || irq_fault ||'''
    text = replace_once(text, old, new)
    path.write_text(text, encoding='utf-8', newline='\n')


def build(args):
    saved = previous.IDENTITY, previous.patch_port
    try:
        previous.IDENTITY = IDENTITY
        previous.patch_port = patch_port
        result = previous.build(args)
    finally:
        previous.IDENTITY, previous.patch_port = saved
    result['ki_response_review'] = dict(fixed_kp=.003389,
        exact_ki_levels=[.001404, .00144, .001476], maximum_motion_seconds=24,
        host_stop_seconds=23.8, maximum_commands=480,
        current_speed_bus_duration_lease_limits_modified=False,
        action_combination_exploration_allowed=False, actor_allowed=False,
        thermal_gate_modified=False, ordinary_deployment_allowed=False,
        previously_measured_point_duration_not_stability_proof=True)
    (Path(args.output) / 'summary.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'arm-bin'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--compiler', default='gcc')
    parser.add_argument('--temp-root', default='E:/simulink/_codex_tmp')
    build(parser.parse_args())
