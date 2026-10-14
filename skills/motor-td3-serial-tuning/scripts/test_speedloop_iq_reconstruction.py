"""Compile the exact v27 generated PI on the host, without hardware imports."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
def run(build,output,compiler):
    build=Path(build);out=Path(output);assert Path('E:/simulink/_codex_tmp').resolve() in out.resolve().parents
    info=json.loads((build/'summary.json').read_text());assert info['build_id']=='g431-speedloop-pi-bidirectional-ref-24s-v27'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert info['bin_sha256']==sha(build/'speedloop-pi-review.bin')=='6c5b9f3f5af480df95ec7c182eaeaffccb7051556ad55855ac675d18e3fd09d9'
    out.mkdir(parents=True,exist_ok=False);own=build/'private-copy/codex-pi';model=build/'private-copy/MATLAB';host=build/'model-tests'
    test=Path(__file__).resolve().parents[1]/'firmware/tests/speedloop_iq_reconstruction_test.c'
    files=[own/n for n in ('motor_td3_speedloop_pi.c','motor_td3_speedloop_pi_bind.c','motor_td3_startup_handover.c')]+[model/'FOC_Model.c',host/'fuzzy_pid.c',test]
    env=dict(os.environ,TEMP=str(out),TMP=str(out),TMPDIR=str(out));exe=out/'iq-reconstruction-test.exe'
    cmd=[compiler,'-std=c99','-O2','-Wall','-Wextra','-ffp-contract=off','-fno-fast-math','-DMOTOR_TD3_SPEEDLOOP_PI_HOST',
        '-I'+str(host),'-I'+str(own),'-I'+str(model),*map(str,files),'-lm','-o',str(exe)]
    c=subprocess.run(cmd,env=env,capture_output=True,text=True);(out/'compile.log').write_text(c.stdout+c.stderr);assert not c.returncode
    c=subprocess.run([str(exe)],env=env,capture_output=True,text=True);(out/'run.log').write_text(c.stdout+c.stderr);assert not c.returncode
    report=json.loads(c.stdout);report.update(source_sha256={str(p):sha(p) for p in files},firmware_sha256=info['bin_sha256'],flash_programmed=False,training_performed=False,actor_applied=False,deployment_allowed=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'}));return report
if __name__=='__main__':
    p=argparse.ArgumentParser();[p.add_argument('--'+n,required=True) for n in ('build','output','compiler')];a=p.parse_args();run(a.build,a.output,a.compiler)
