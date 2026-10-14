"""Private, finite 24s continuous acquisition build. No hardware access.

Single startup, original handover/FOC, exact baseline/+4% Kp only, fixed Ki.
Changes duration and repeated references explicitly; never an Actor release.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_excitation_evidence as previous
import build_speedloop_excitation_review as excitation
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-continuous-24s-v13'
EXCITATION_PATCH=excitation.patch_port


def patch_port(path,motion=False):
    EXCITATION_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'.trial_max_us=8000000U,.command_max=160U',
                     '.trial_max_us=24000000U,.command_max=480U')
    text=replace_once(text,'return elapsed>=3800000ULL && elapsed<7100000ULL;',
                     'return elapsed>=3800000ULL && elapsed<23100000ULL;')
    text=replace_once(text,'''    if(elapsed<4000000ULL) return 1000.0f;
    if(elapsed<5200000ULL) return 1100.0f;
    if(elapsed<6400000ULL) return 900.0f;
    return 1000.0f;''','''    if(elapsed<4000000ULL || elapsed>=22000000ULL) return 1000.0f;
    uint64_t phase=(elapsed-4000000ULL)%3600000ULL;
    return phase<1200000ULL?1100.0f:phase<2400000ULL?900.0f:1000.0f;''')
    path.write_text(text,encoding='utf-8',newline='\n')
    timing=path.parent/'motor_td3_trial_timing.h'
    t=timing.read_text(encoding='utf-8')
    t=replace_once(t,'TD3_REVIEW_TOTAL_US 8000000ULL','TD3_REVIEW_TOTAL_US 24000000ULL')
    t=replace_once(t,'TD3_REVIEW_CLOSED_US 5800000ULL','TD3_REVIEW_CLOSED_US 21800000ULL')
    timing.write_text(t,encoding='utf-8',newline='\n')


def build(a):
    # Bind the custom port at the same level as v12; never change old identities.
    saved=previous.IDENTITY,excitation.patch_port
    try:
        previous.IDENTITY=IDENTITY
        excitation.patch_port=patch_port
        report=previous.build(a)
    finally: previous.IDENTITY,excitation.patch_port=saved
    report['continuous_review']=dict(maximum_motion_seconds=24,host_stop_seconds=23.8,
        single_startup=True,command_max=480,command_interval_ms=50,
        reference_cycle_start_ms=4000,reference_cycle_ms=3600,
        reference_cycle_rpm=[1100,900,1000],reference_final_baseline_ms=22000,
        probe_source_elapsed_ms=[3900,23000],probe_application_elapsed_ms=[3800,23100],
        baseline_kp=.003389,probe_kp=.00352456,fixed_ki=.00144,
        actor_allowed=False,thermal_gate_modified=False,physical_validation_passed=False,
        deployment_allowed=False,performance_claim_allowed=False,
        independent_cpu_stall_watchdog_integrated=False)
    report['duration_contract_changed']=True
    report['evidence_review'].update(control_equivalent_to=None,control_modified=True,limits_modified=True)
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
