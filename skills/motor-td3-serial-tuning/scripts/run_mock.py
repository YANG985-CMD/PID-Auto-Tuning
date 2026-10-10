#!/usr/bin/env python3
"""One-command mock bridge -> actual MATLAB TD3 -> evaluation -> C parity run."""
import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from actor_codegen import export, verify
from session_checks import audit_rows, decode_json, load_json


def matlab_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def run(output, matlab, compiler, rounds):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new empty output directory; existing runs are not overwritten')
    output.mkdir(parents=True,exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    token = secrets.token_hex(32)
    token_file = output/'bridge-token.txt'
    token_file.write_text(token,encoding='utf-8')
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1',TEMP=str(output),TMP=str(output))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    bridge_args = [sys.executable,'-B',str(root/'scripts/motor_runtime.py'),
                   '--profile',str(root/'assets/mock-profile.json'),'--output',str(output/'bridge'),
                   '--token-file',str(token_file),'--port',str(port)]
    with (output/'bridge-stdout.txt').open('w') as out, (output/'bridge-stderr.txt').open('w') as err:
        bridge = subprocess.Popen(bridge_args,stdout=out,stderr=err,env=env,creationflags=flags)
        try:
            ready=False
            for _ in range(100):
                if bridge.poll() is not None:
                    raise RuntimeError('Bridge exited; see bridge-stderr.txt')
                if (output/'bridge-stdout.txt').read_text().strip():
                    ready=True; break
                time.sleep(.05)
            if not ready: raise RuntimeError('Bridge start timed out')
            script = ("addpath("+matlab_quote(root/'matlab')+"); "
                      "trainMotorTD3("+str(port)+","+matlab_quote(token_file)+","+
                      matlab_quote(output/'matlab')+","+str(rounds)+"); "
                      "c=MotorTD3Client("+str(port)+","+matlab_quote(token_file)+"); c.call(struct('op','shutdown')); ")
            print('Bridge ready. Running actual MATLAB TD3; motor hardware is not connected.',flush=True)
            with (output/'matlab-stdout.txt').open('w') as m_out, (output/'matlab-stderr.txt').open('w') as m_err:
                subprocess.run([matlab,'-batch',script],cwd=output,env=env,stdout=m_out,stderr=m_err,
                               check=True,creationflags=flags,timeout=1200)
            bridge.wait(timeout=5)
        finally:
            if bridge.poll() is None:
                bridge.terminate()
                bridge.wait(timeout=5)
    model=output/'matlab/actor/actor.json'
    manifest=export(model,output/'actor-c')
    parity=verify(output/'actor-c',output/'matlab/actor/matlab-reference.json',compiler)
    with (output/'bridge/transitions.jsonl').open(encoding='utf-8') as stream:
        audit=audit_rows([decode_json(line) for line in stream if line.strip()],load_json(root/'assets/mock-profile.json'))
    training=load_json(output/'matlab/training-summary.json')
    if not audit['trainable'] or not training['actor_weight_change_l2'] > 0:
        raise RuntimeError('Causal replay audit or actual TD3 update verification failed')
    summary=dict(passed=True,hardware_access=False,training=training,audit=audit,c_parity=parity,
                 evaluation=load_json(output/'matlab/evaluation-summary.json'),deployment_manifest=manifest)
    (output/'run-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,replay_experiences=training['replay_experiences'],
                         actor_weight_change_l2=training['actor_weight_change_l2'],
                         host_c_parity_passed=parity['host_c_parity_passed'],
                         candidate_rmse_better=summary['evaluation']['candidate_rmse_better'],
                         hardware_deployment_approved=False),indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--matlab',default=shutil.which('matlab'))
    parser.add_argument('--compiler',default=shutil.which('gcc'))
    parser.add_argument('--rounds',type=int,default=6)
    args=parser.parse_args()
    if not args.matlab or not args.compiler or args.rounds<2:
        parser.error('MATLAB, gcc and at least two rounds are required')
    run(args.output,args.matlab,args.compiler,args.rounds)
