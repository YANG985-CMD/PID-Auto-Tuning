"""Three 8s training-only probes, 24s reserved, fault stops whole batch."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import speedloop_binary_probe as probe


def run(a):
    a.probe_schedule_index=0;a.gain_mode='kp_probe';probe.validate(a)
    if not a.power_confirmed or not a.authorized_no_thermal_trial:
        raise ValueError('Site state and bounded exception required')
    out=Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,utc=datetime.now(timezone.utc).isoformat(),passed=False,
        requested_rounds=3,maximum_motion_seconds=8,reserved_batch_motion_seconds=24,
        minimum_cooldown_seconds=30,probe_slot_ms=250,probe_source_elapsed_ms=[3900,6900],
        probe_patterns=[list(p) for p in probe.PATTERNS],split='training only; existing whole-pair holdout unchanged',
        actor_applied=False,td3_training_performed=False,ordinary_deployment_allowed=False,
        performance_claim_allowed=False,temperature_gate_modified=False,rounds=[],failure=None)
    def save():
        (out/'collection-summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    script=Path(__file__).with_name('speedloop_binary_probe.py')
    for index in range(3):
        if index:
            print('Verified stop; cooling at least 30s.',flush=True);time.sleep(30)
        dest=out/f'round-{index+1:02d}'
        row=dict(round=index+1,probe_schedule_index=index,reserved_motion_seconds=8,passed=False)
        report['rounds'].append(row);save()
        for phase in ('prepare','trial'):
            cmd=[sys.executable,'-B',str(script),phase,'--build',a.build,'--nm',a.nm,
                '--output',str(dest/phase),'--authorized-binary-probe','--probe-schedule-index',str(index)]
            if phase=='prepare':cmd+=['--energized-phase-inhibited-confirmed']
            else:cmd+=['--boot-token-file',str(dest/'prepare/boot-token.txt'),'--power-confirmed','--authorized-no-thermal-trial']
            try:result=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
            except subprocess.TimeoutExpired:
                report['failure']=f'{phase} exceeded deadline; no retry';save();return report
            dest.mkdir(exist_ok=True)
            (dest/(phase+'.stdout.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
            f=dest/phase/'summary.json';info=json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
            if result.returncode or not info.get('passed'):
                report['failure']=f'{phase} failed round {index+1}; no retry';save();return report
            if phase=='trial':
                row.update(passed=all(info[k] for k in ('protocol_stop_acknowledged',
                    'core_halted_after_physical_shutdown','can_released_after_shutdown')) and
                    info['final_irq_fault']==info['final_tx_fault']==0,
                    actual_motion_ms=(info['trial_timing']['last_us']-info['trial_timing']['started_us'])/1000,
                    fault=info['final_irq_fault'],tx_fault=info['final_tx_fault'])
                save();print(json.dumps(row),flush=True)
                if not row['passed']:
                    report['failure']='Final shutdown/fault check failed; no retry';save();return report
    report['passed']=True;save();return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    for name in ('authorized-binary-probe','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
