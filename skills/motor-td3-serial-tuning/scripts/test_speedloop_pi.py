"""Compile and check the PI gain owner. No motor, probe, CAN or serial access."""
import argparse
import json
import os
import subprocess
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]


def run_checks(out,compiler):
    out=Path(out).resolve()
    if os.name=='nt' and Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Windows temporary output must be under E:/simulink/_codex_tmp')
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh empty task directory')
    out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    fw=SKILL/'firmware';exe=out/('pi-test.exe' if os.name=='nt' else 'pi-test')
    result=subprocess.run([compiler,'-std=c99','-O2','-pipe','-Wall','-Wextra','-Werror',
        '-ffp-contract=off','-fno-fast-math','-I'+str(fw),str(fw/'motor_td3_speedloop_pi.c'),
        str(fw/'tests/speedloop_pi_test.c'),'-lm','-o',str(exe)],env=env,capture_output=True,text=True)
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode: raise RuntimeError('PI compilation failed; inspect build.log')
    result=subprocess.run([str(exe)],cwd=out,env=env,capture_output=True,text=True)
    (out/'checks.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode: raise RuntimeError('PI check failed; inspect checks.log')
    summary=json.loads(result.stdout)
    summary.update(schema_version=1,scope='host C gain owner and bumpless parameter changes',
        hardware_accessed=False,motion_approved=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True);p.add_argument('--compiler',default='gcc')
    a=p.parse_args();print(json.dumps(run_checks(a.output,a.compiler)))
