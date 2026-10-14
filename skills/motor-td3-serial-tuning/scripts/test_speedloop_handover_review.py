"""Actual corrected model and adapter checks without hardware."""
import argparse,json,os,subprocess
from pathlib import Path
import test_speedloop_startup_trace as startup
import test_speedloop_duration_review as duration
from build_speedloop_handover_review import IDENTITY

def run(build,output,compiler):
    out=Path(output).resolve();b=Path(build).resolve();root=Path('E:/simulink/_codex_tmp').resolve()
    if root not in out.parents:raise ValueError('Use temporary root')
    saved=startup.IDENTITY
    try:
        startup.IDENTITY=IDENTITY
        adapter=startup.run(b,out/'adapter',compiler)
    finally:startup.IDENTITY=saved
    own=b/'private-copy/codex-pi';model=b/'private-copy/MATLAB';host=b/'model-tests'
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    # The adapter harness above needs the helper translation unit; compile it
    # explicitly for the complete model handover test too.
    files=[own/n for n in ('motor_td3_speedloop_pi.c','motor_td3_speedloop_pi_bind.c','motor_td3_startup_handover.c')]
    exe=out/'handover-test.exe'
    cmd=[compiler,'-std=c99','-O2','-Wall','-Wextra','-ffp-contract=off','-fno-fast-math',
         '-DMOTOR_TD3_SPEEDLOOP_PI_HOST','-I'+str(host),'-I'+str(own),'-I'+str(model),
         *map(str,files),str(model/'FOC_Model.c'),str(host/'fuzzy_pid.c'),
         str(Path(__file__).resolve().parents[1]/'firmware/tests/speedloop_handover_test.c'),'-lm','-o',str(exe)]
    c=subprocess.run(cmd,capture_output=True,text=True,env=env)
    (out/'model-compile.log').write_text(c.stdout+c.stderr,encoding='utf-8');assert c.returncode==0
    r=subprocess.run([str(exe)],capture_output=True,text=True,env=env)
    (out/'model-run.log').write_text(r.stdout+r.stderr,encoding='utf-8');assert r.returncode==0
    report=dict(adapter=adapter,model=json.loads(r.stdout),passed=True,hardware_accessed=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','compiler'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.build,a.output,a.compiler)
