"""Three v12 development pairs, 48s reserved; complete-pair holdout.

All references, gains, protection limits and Ki are fixed in the exact image.
No Actor application. A failure consumes/ends this batch, without retry.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import speedloop_excitation_evidence as review
PAIR_SCRIPT='collect_speedloop_excitation_evidence.py'
SCOPE_FLAG='--authorized-excitation-evidence'
COLLECTION_SOURCE='real_motor_excitation_evidence'


def run(a):
    review.validate(a)
    if not a.power_confirmed or not a.authorized_no_thermal_trial:
        raise ValueError('Physical state and bounded exception required')
    out=Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Use task temporary root')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,utc=datetime.now(timezone.utc).isoformat(),passed=False,
        source=COLLECTION_SOURCE,reserved_total_motion_seconds=48,
        round_cap_seconds=8,pair_cap_seconds=16,cooldown_seconds=30,
        orders=['probe-first','baseline-first','probe-first'],
        primary_evaluation_elapsed_ms=[4000,7700],
        secondary_intervals_elapsed_ms=[[4000,5200],[5200,6400],[6400,7700]],
        new_training_pairs=[1,2],new_validation_pairs=[3],
        split_unit='both complete boot sessions of a pair',
        validation_not_used_for_reward_scaling_or_updates=True,
        required_rmse_reduction_percent=5,actor_applied=False,ki_fixed=.00144,
        temperature_gate_modified=False,ordinary_deployment_allowed=False,
        performance_claim_allowed=False,pairs=[],failure=None)
    def save():
        (out/'session-summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    script=Path(__file__).with_name(PAIR_SCRIPT)
    for i,order in enumerate(report['orders'],1):
        if i>1:
            print('Pair stopped; cooling at least 30s before next pair.',flush=True)
            time.sleep(30)
        dest=out/f'pair-{i:02d}'
        row=dict(pair=i,order=order,validation_split=i in report['new_validation_pairs'],passed=False)
        report['pairs'].append(row);save()
        cmd=[sys.executable,'-B',str(script),'--build',a.build,'--output',str(dest),
             '--nm',a.nm,'--order',order,SCOPE_FLAG,
             '--power-confirmed','--authorized-no-thermal-trial']
        result=subprocess.run(cmd,capture_output=True,text=True)
        (out/f'pair-{i:02d}.stdout.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
        p=dest/'collection-summary.json'
        info=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        row.update(passed=result.returncode==0 and info.get('passed',False),
                   actual_motion_ms=sum(r.get('actual_motion_ms',0) for r in info.get('rounds',[])))
        save();print(json.dumps(row),flush=True)
        if not row['passed']:
            report['failure']=info.get('failure') or f'Pair {i} failed; no retry'
            save();return report
    report['passed']=True;save();return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-excitation-evidence','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
