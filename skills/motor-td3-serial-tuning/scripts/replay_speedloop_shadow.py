"""Paced replay of previously recorded motor data through the actual MATLAB TCP Actor.

Never connects to CAN, UART or a debugger. Does not create training experience.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from speedloop_shadow import ShadowClient


def replay(telemetry_file, output, port, token_file):
    output = Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents:
        raise ValueError('Use the approved temporary root')
    output.mkdir(parents=True, exist_ok=True)
    original = Path(telemetry_file).read_bytes()
    rows = [json.loads(line) for line in original.splitlines() if line.strip()]
    assert rows and all(b['t_us']>a['t_us'] and b['seq']==a['seq']+1 for a,b in zip(rows,rows[1:]))
    client = ShadowClient(port, token_file)
    records = []
    try:
        if not client.ready.wait(2): raise RuntimeError('MATLAB not ready: '+str(client.error))
        started=time.perf_counter()
        for row in rows:
            due=started+(row['t_us']-rows[0]['t_us'])/1e6
            while time.perf_counter()<due:
                records.extend(client.drain())
                time.sleep(min(.001,max(0,due-time.perf_counter())))
            client.submit(row, source='recorded_motor_replay')
            records.extend(client.drain())
        until=time.perf_counter()+.3
        while time.perf_counter()<until:
            records.extend(client.drain()); time.sleep(.005)
    finally:
        closed=client.close(); records.extend(client.drain())
    summary=client.summary(records)
    summary.update(hardware_accessed=False, motor_motion_started=False,
                   source='paced_replay_of_recorded_real_motor_telemetry',
                   source_telemetry_sha256=hashlib.sha256(original).hexdigest(),
                   worker_closed=closed, motor_performance_evaluated=False)
    summary['passed']=bool(closed and not client.error and summary['accepted']>=20 and
                           not summary['records_dropped'])
    with (output/'shadow-predictions.jsonl').open('w',encoding='utf-8') as f:
        for record in records: f.write(json.dumps(record,allow_nan=False)+'\n')
    (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,allow_nan=False))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('telemetry','output','token-file'): parser.add_argument('--'+key,required=True)
    parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    raise SystemExit(0 if replay(args.telemetry,args.output,args.port,args.token_file)['passed'] else 1)
