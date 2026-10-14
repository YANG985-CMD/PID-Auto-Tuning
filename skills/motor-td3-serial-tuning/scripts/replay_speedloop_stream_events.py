"""Exercise rolling-window audit on an ALREADY completed real trial.

Uses retained final stage timing proof; this is historical playback, never
claims new physical collection or real-time stage-proof latency.
"""
import argparse
import json
from pathlib import Path
from speedloop_response_windows import lines
from speedloop_stream_training import CausalStream


def run(trial,output):
    trial,out=Path(trial).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    summary=json.loads((trial/'summary.json').read_text(encoding='utf-8'))
    if not summary['passed'] or summary['final_irq_fault'] or summary['final_tx_fault']:raise ValueError('Faulted trial')
    if not all(summary[k] for k in ('protocol_stop_acknowledged','core_halted_after_physical_shutdown','can_released_after_shutdown')):
        raise ValueError('Missing historical shutdown evidence')
    packets=lines(trial/'telemetry.jsonl');commands=lines(trial/'commands.jsonl')
    bytime={p['t_us']:p for p in packets}
    events=[(p['host_received_monotonic'],1,p) for p in packets]
    events.extend((c['host_monotonic'],0,c) for c in commands)
    stream=CausalStream();out.mkdir(parents=True,exist_ok=False)
    stage=dict(summary['trial_timing'],irq_fault=0)
    for _,kind,value in sorted(events,key=lambda x:(x[0],x[1])):
        if kind==0:stream.command(value,bytime.get(value['source_t_us']))
        else:
            row=stream.telemetry(value,stage if value['enabled'] else None)
            if row:(out/f'window-{stream.windows:05d}.json').write_text(json.dumps(row,allow_nan=False)+'\n',encoding='utf-8')
    result=dict(historical_playback=True,hardware_accessed=False,new_physical_trials=0,
        rolling_windows=stream.windows,rejected_short_groups=stream.rejected)
    (out/'playback-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (out/'session-ended.json').write_text(json.dumps(dict(physical_trial_passed=True,stop_acknowledged=True,
        core_halted=True,can_released=True,final_irq_fault=0,final_tx_fault=0,historical_playback=True))+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.trial,a.output)
