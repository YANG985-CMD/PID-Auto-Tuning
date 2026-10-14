"""Three bounded paired batches, 48s reserved total, stop on the first failure.

Pre-register phase metrics before opening hardware. One collector owns the board
at a time; every round has the existing 8s MCU cap and the exact v7 image gate.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import speedloop_response_review as review


def run(a):
    review.validate(a)
    if not a.power_confirmed or not a.authorized_no_thermal_trial:
        raise ValueError('Physical state and no-thermal experiment scope required')
    out=Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,utc=datetime.now(timezone.utc).isoformat(),passed=False,
        reserved_total_motion_seconds=48,round_cap_seconds=8,pair_cap_seconds=16,
        cooldown_seconds=30,orders=['probe-first','baseline-first','probe-first'],
        primary_evaluation_elapsed_ms=[4000,7700],secondary_probe_evaluation_elapsed_ms=[5100,6000],
        required_rmse_reduction_percent=5,no_increase_in_nominal_peak_current=True,
        no_increase_in_peak_speed=True,actor_applied=False,temperature_gate_modified=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False,pairs=[],failure=None)
    def save():
        (out/'session-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    for i,order in enumerate(report['orders'],1):
        if i>1:
            print('Pair stopped and verified; waiting at least 30s before the next pair.',flush=True)
            time.sleep(30)
        dest=out/f'pair-{i:02d}'
        row=dict(pair=i,order=order,reserved_motion_seconds=16,passed=False)
        report['pairs'].append(row);save()
        cmd=[sys.executable,'-B',str(Path(__file__).with_name('collect_speedloop_response.py')),
            '--build',a.build,'--output',str(dest),'--nm',a.nm,'--order',order,
            '--authorized-response-review','--power-confirmed','--authorized-no-thermal-trial']
        result=subprocess.run(cmd,capture_output=True,text=True)
        (out/f'pair-{i:02d}.stdout.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
        p=dest/'collection-summary.json'
        info=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        row['passed']=bool(result.returncode==0 and info.get('passed'))
        row['actual_motion_ms']=sum(r.get('actual_motion_ms',0) for r in info.get('rounds',[]))
        if not row['passed']:
            report['failure']=info.get('failure') or f'Pair {i} failed; no retry'
            save();print(json.dumps(report),flush=True);return report
        save();print(json.dumps(row),flush=True)
    report['passed']=True;save();print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-response-review','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
