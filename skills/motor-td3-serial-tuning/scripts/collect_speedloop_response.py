"""One local batch: baseline then prescribed Kp response, at most 2 x 8s.

Existing output directories cannot be resumed/retried. Reserve the full trial
budget before issuing commands. Abort on any preparation/trial/stop failure.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import speedloop_response_review as review

REVIEW_SCRIPT='speedloop_response_review.py'
SCOPE_FLAG='--authorized-response-review'
COLLECTION_SOURCE='real_motor_response_review'


def run(a):
    review.validate(a)
    if not a.power_confirmed or not a.authorized_no_thermal_trial:
        raise ValueError('Current site state and bounded no-thermal scope required')
    order=getattr(a,'order','baseline-first')
    if order not in ('baseline-first','probe-first'):raise ValueError('Unknown paired order')
    modes=('baseline','kp_probe') if order=='baseline-first' else ('kp_probe','baseline')
    out=Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Use the approved temporary root')
    out.mkdir(parents=True,exist_ok=False) # No retry/resume with a consumed budget.
    report=dict(schema_version=1,source=COLLECTION_SOURCE,passed=False,
        utc=datetime.now(timezone.utc).isoformat(),requested_rounds=2,
        maximum_motion_seconds=8,reserved_batch_motion_seconds=16,
        minimum_cooldown_seconds=30,actor_applied=False,td3_training_performed=False,
        temperature_gate_modified=False,ordinary_deployment_allowed=False,
        performance_claim_allowed=False,order=list(modes),rounds=[],failure=None)
    def save():
        (out/'collection-summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    script=Path(__file__).with_name(REVIEW_SCRIPT)
    common=['--build',a.build,'--nm',a.nm,SCOPE_FLAG]
    for i,mode in enumerate(modes,1):
        if i>1:
            print('First round stopped and verified. Cooling down for at least 30 seconds.',flush=True)
            time.sleep(30)
        dest=out/f'round-{i:02d}-{mode}'
        dest.mkdir()
        row=dict(round=i,mode=mode,reserved_motion_seconds=8,passed=False)
        report['rounds'].append(row);save()
        for phase in ('prepare','trial'):
            cmd=[sys.executable,'-B',str(script),phase,*common,'--output',str(dest/phase),
                 '--gain-mode',mode]
            if phase=='prepare':cmd+=['--energized-phase-inhibited-confirmed']
            else:cmd+=['--boot-token-file',str(dest/'prepare/boot-token.txt'),
                       '--power-confirmed','--authorized-no-thermal-trial']
            try:
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
            except subprocess.TimeoutExpired:
                report['failure']=f'{phase} process exceeded deadline in round {i}; no retry'
                save();print(json.dumps(report),flush=True);return report
            (dest/(phase+'.stdout.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
            p=dest/phase/'summary.json'
            info=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
            if result.returncode or not info.get('passed'):
                report['failure']=f'{phase} failed in round {i}: '+str(info.get('error') or info.get('shutdown_error') or 'see phase output')
                save();print(json.dumps(report),flush=True);return report
            if phase=='trial':
                row.update(passed=True,actual_motion_ms=(info['trial_timing']['last_us']-info['trial_timing']['started_us'])/1000,
                    fault=info['final_irq_fault'],tx_fault=info['final_tx_fault'],
                    stop_acknowledged=info['protocol_stop_acknowledged'],
                    core_halted=info['core_halted_after_physical_shutdown'],
                    can_released=info['can_released_after_shutdown'],
                    telemetry_packets=info['complete_telemetry_packets'])
                if row['fault'] or row['tx_fault'] or not all(row[k] for k in ('stop_acknowledged','core_halted','can_released')):
                    report['failure']=f'Final stop verification failed in round {i}';save();return report
                save();print(json.dumps(row),flush=True)
    report['passed']=True;save();print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-response-review','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    p.add_argument('--order',choices=('baseline-first','probe-first'),default='baseline-first')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
