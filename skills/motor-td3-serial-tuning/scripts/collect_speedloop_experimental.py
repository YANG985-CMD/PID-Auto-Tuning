"""Collect a separately authorized bounded, fixed-behavior physical dataset.

Each trial uses the sealed motion-v5 image and its existing 3 s hard limit.
No learned/random policy, gradient calculations, Flash, or automatic fault retry.
Cooling pauses are an operating schedule, not a measured thermal protection.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


def validate_budget(rounds, budget, cooldown, authorized):
    if not authorized:
        raise ValueError('Explicit user authorization for the cumulative experiment budget is required')
    if not 1 <= rounds <= 16 or not rounds*3 <= budget <= 48 or cooldown < 30:
        raise ValueError('Allowed schedule: at most 16 x 3 s, budget <=48 s, pauses >=30 s')


def hall_stable(uid):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    from speedloop_motion_handshake import REGS, PHASE_MASK
    session=ConnectHelper.session_with_chosen_probe(unique_id=uid,target_override='cortex_m',
        connect_mode='attach',frequency=1000000,no_config=True,blocking=False,
        options={'resume_on_disconnect':False,'cache.enable_memory':False,'cache.enable_register':False})
    if session is None: raise RuntimeError('Selected probe is unavailable')
    with session:
        t=session.target
        if (t.get_state()!=Target.State.HALTED or t.read32(REGS['tim1_bdtr'])&0x8000 or
                t.read32(REGS['tim1_ccer'])&PHASE_MASK or t.read32(0x4002104c)&3!=3):
            raise RuntimeError('Stopped board state/clock prerequisites changed')
        codes=[];due=time.monotonic()+.5
        while time.monotonic()<due:
            pins=t.read32(0x48000410)
            codes.append(((pins>>8)&1)|((pins>>6)&2)|((pins>>4)&4))
            time.sleep(.017)
        if len(set(codes))!=1 or codes[0] not in range(1,7):
            raise RuntimeError('Hall input changed or is invalid during the stopped preflight')
        return dict(stable_code=codes[0],samples=len(codes),observation_seconds=.5,
                    note='Stable Hall code check; not an independent zero-speed measurement')


def collect(a):
    validate_budget(a.rounds,a.maximum_motion_seconds,a.cooldown_seconds,a.authorized_experiment_budget)
    out=Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents or out.exists():
        raise ValueError('Use a new task directory beneath the approved temporary root')
    out.mkdir(parents=True)
    scripts=Path(__file__).resolve().parent
    report=dict(schema_version=1,started_utc=datetime.now(timezone.utc).isoformat(),
                passed=False,hardware_accessed=True,authorized_rounds=a.rounds,
                authorized_maximum_motion_seconds=a.maximum_motion_seconds,
                reserved_motion_seconds=0,cooldown_seconds=a.cooldown_seconds,trials=[],
                fixed_behavior=True,td3_training_performed=False,actor_deployed=False,
                thermal_exception='user-approved bounded dataset collection only; normal gates unchanged')
    def save(): (out/'collection-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    def run(script,args,folder):
        r=subprocess.run([sys.executable,'-B',str(scripts/script),*args],capture_output=True,text=True,timeout=30)
        (folder/(script+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode: raise RuntimeError(script+' failed; do not retry automatically')
    save()
    try:
        for index in range(a.rounds):
            if index:
                print(json.dumps(dict(event='cooldown',seconds=a.cooldown_seconds)),flush=True)
                time.sleep(a.cooldown_seconds)
            # Every episode retains its own source files, identity and stop log.
            trial=out/f'trial-{index+1:02d}';trial.mkdir()
            stopped=hall_stable(a.uid)
            report['reserved_motion_seconds']+=3
            save() # Reserve before BEGIN, including interrupted/failed attempts.
            prepare=trial/'prepare';capture=trial/'run'
            common=['--build',a.build,'--nm',a.nm,'--uid',a.uid]
            run('speedloop_motion_prepare.py',common+['--output',str(prepare),
                '--energized-phase-inhibited-confirmed'],trial)
            run('speedloop_motion_gain_trial.py',common+['--output',str(capture),
                '--boot-token-file',str(prepare/'boot-token.txt'),'--power-confirmed',
                '--authorized-no-thermal-trial'],trial)
            summary=json.loads((capture/'summary.json').read_text(encoding='utf-8'))
            if (not summary['passed'] or not summary['core_halted_after_physical_shutdown'] or
                    not summary['protocol_stop_acknowledged'] or summary['final_irq_fault'] or
                    summary['final_tx_fault']):
                raise RuntimeError('Trial stopped/failed; no next episode is permitted')
            report['trials'].append(dict(index=index+1,run_dir=str(capture),hall_preflight=stopped,
                complete_telemetry_packets=summary['complete_telemetry_packets'],
                actual_gain_commands=summary['actual_gain_commands'],
                nominal_peak_current_a=summary['nominal_peak_current_a']))
            save()
            print(json.dumps(dict(event='trial_complete',index=index+1,run_dir=str(capture),
                                  actual_gain_commands=summary['actual_gain_commands'])),flush=True)
        report['passed']=True
    except (Exception,KeyboardInterrupt) as error:
        report['error']=str(error) or 'Interrupted by operator'
        report['automatic_retry']=False
    finally:
        save()
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','output','nm'):p.add_argument('--'+key,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--rounds',type=int,default=16)
    p.add_argument('--maximum-motion-seconds',type=int,default=48)
    p.add_argument('--cooldown-seconds',type=int,default=30)
    p.add_argument('--authorized-experiment-budget',action='store_true')
    args=p.parse_args();raise SystemExit(0 if collect(args)['passed'] else 1)
