"""Validate real delayed ACK against MCU application time, reject lost lease."""
import argparse,contextlib,io,json,shutil,tempfile
from pathlib import Path
from audit_speedloop_reference_v26 import audit
import speedloop_reference_support_probe as profile

def run(folder,contract,output):
    folder,contract,output=map(Path,(folder,contract,output))
    assert Path('E:/simulink/_codex_tmp').resolve() in output.resolve().parents
    output.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        root=Path(tmp)
        for name in ('trial/summary.json','trial/telemetry.jsonl','stream/events.jsonl'):
            dst=root/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(folder/name,dst)
        with contextlib.redirect_stdout(io.StringIO()):
            positive=audit(root,contract,1,root/'positive.json',runtime_profile=profile)
        assert max(r['telemetry_ACK_delay_ms'] for r in positive['actual_slots'])>100
        assert max(r['actual_apply_delay_ms'] for r in positive['actual_slots'])<100
        events_path=root/'stream/events.jsonl'
        events=[json.loads(line) for line in events_path.read_text().splitlines()]
        packet=next(r['packet'] for r in events if r['kind']=='telemetry' and r['packet']['elapsed_ms']>8800
            and r['packet']['applied_seq']>0)
        seq=packet['applied_seq'];command=next(r['command'] for r in events if r['kind']=='command'
            and r['command']['type']=='gains' and r['command']['command_seq']==seq)
        packet['t_apply_us']=command['expires_us']+1
        events_path.write_text(''.join(json.dumps(r)+'\n' for r in events))
        rejected=False
        try:
            audit(root,contract,1,root/'rejected.json',runtime_profile=profile)
        except ValueError as err:
            assert 'acknowledgement' in str(err);rejected=True
        assert rejected
    report=dict(passed=True,real_late_report_validated_by_actual_application_time=True,
        telemetry_ACK_max_ms=max(r['telemetry_ACK_delay_ms'] for r in positive['actual_slots']),
        actual_application_max_ms=max(r['actual_apply_delay_ms'] for r in positive['actual_slots']),
        expired_actual_application_rejected=True,hardware_accessed=False,new_motor_data=False,
        timing_boundary_increased=False,corrupted_copy_removed=True)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return report

if __name__=='__main__':
    p=argparse.ArgumentParser();
    for key in ('folder','contract','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();run(a.folder,a.contract,a.output)
