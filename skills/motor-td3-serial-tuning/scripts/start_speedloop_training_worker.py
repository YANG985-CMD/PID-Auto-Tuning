"""Launch one hidden MATLAB batch process. No CAN/probe/Flash/motor access."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def literal(path):return "\""+str(Path(path).resolve()).replace('"','""')+"\""


def run(a):
    launch=Path(a.launch).resolve();root=Path('E:/simulink/_codex_tmp').resolve()
    if (not Path(a.checkpoint).is_file() or not Path(a.prior).is_dir()
            or not (Path(a.prior)/'window-summary.json').is_file()
            or not (Path(a.prior)/'response-windows.jsonl').is_file()):
        raise ValueError('Checkpoint file and prior DATASET DIRECTORY are required before launching MATLAB')
    if root not in launch.parents or root not in Path(a.output).resolve().parents:
        raise ValueError('Use task temporary root')
    launch.mkdir(parents=True,exist_ok=False)
    entry=launch/'worker_entry.m'
    source=Path(__file__).resolve().parents[1]/'matlab'
    entry.write_text('addpath('+literal(source)+');\n'
        'runSpeedLoopAsyncTraining('+','.join(literal(p) for p in
        (a.checkpoint,a.prior,a.stream,a.output))+',180,"'+getattr(a,'gain_profile','two')+'");\n',encoding='utf-8')
    env=os.environ.copy();env.update(TEMP=str(launch),TMP=str(launch),TMPDIR=str(launch),
                                    MATLAB_PREFDIR=str(launch/'matlab-prefs'))
    startup=None;flags=0
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=0;flags=subprocess.CREATE_NO_WINDOW
    with (launch/'worker.log').open('wb') as log:
        command=[a.matlab,'-batch',"run('"+str(entry).replace("'","''")+"')"]
        child=subprocess.Popen(command,cwd=launch,env=env,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,startupinfo=startup,creationflags=flags)
    result=dict(pid=child.pid,hardware_accessed=False,entry=str(entry),output=a.output,stream=a.stream)
    (launch/'process.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('matlab','checkpoint','prior','stream','output','launch'):p.add_argument('--'+name,required=True)
    p.add_argument('--gain-profile',choices=('two','interior3','lower4','lower8'),default='two')
    run(p.parse_args())
