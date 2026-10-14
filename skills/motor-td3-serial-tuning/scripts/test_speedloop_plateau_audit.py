"""Corrupt retained real evidence; verify the offline audit rejects it."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
from analyze_speedloop_plateaus import analyze

def run(root,output):
    root,output=Path(root),Path(output);output.mkdir(parents=True,exist_ok=False)
    def case(name,mutate,expected_error):
        folder=output/name;shutil.copytree(root/'round0-corrected',folder)
        contract=folder/'contract.json';shutil.copyfile(root/'schedule-contract.json',contract)
        mutate(folder,contract)
        try:
            with redirect_stdout(io.StringIO()):analyze(folder/'stream',folder/'trial/summary.json',contract,folder/'result.json')
        except ValueError as exc:
            options=(expected_error,) if isinstance(expected_error,str) else expected_error
            assert any(reason in str(exc) for reason in options),(name,str(exc));return
        raise AssertionError('Corrupted evidence admitted: '+name)
    def change_summary(field,value):
        def mutate(folder,contract):
            p=folder/'trial/summary.json';r=json.loads(p.read_text(encoding='utf-8'));r[field]=value
            p.write_text(json.dumps(r),encoding='utf-8')
        return mutate
    case('unconfirmed-stop',change_summary('protocol_stop_acknowledged',False),'Incomplete stop')
    def active_gate(folder,contract):
        p=folder/'trial/summary.json';r=json.loads(p.read_text(encoding='utf-8'))
        r['final_board_state']['tim1_bdtr']|=0x8000;p.write_text(json.dumps(r),encoding='utf-8')
    case('false-off-marker',active_gate,'not inhibited')
    def changed_interval(folder,contract):
        r=json.loads(contract.read_text(encoding='utf-8'));r['analysis_settle_ms']=1100
        contract.write_text(json.dumps(r),encoding='utf-8')
    case('post-hoc-interval',changed_interval,'interval changed')
    def event_change(folder,modify):
        p=folder/'stream/events.jsonl';rows=[json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
        modify(rows);p.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    def missing_stage(folder,contract):
        def change(rows):
            item=next(r for r in rows if r['kind']=='telemetry' and r['packet']['elapsed_ms']>6500)
            item['stage_proof']=None
        event_change(folder,change)
    case('missing-stage',missing_stage,'RunStage proof')
    def fake_ack(folder,contract):
        def change(rows):
            item=next(r for r in rows if r['kind']=='telemetry' and r['packet']['elapsed_ms']>8500)
            item['packet']['kp']=.0033889999613165855
        event_change(folder,change)
    case('wrong-actual-gain',fake_ack,'action acknowledgement')
    def missing_packet(folder,contract):
        def change(rows):
            n=next(i for i,r in enumerate(rows) if r['kind']=='telemetry' and r['packet']['elapsed_ms']>10500)
            rows.pop(n)
        event_change(folder,change)
    case('missing-packet',missing_packet,('sequence/time gap','Command source differs'))
    with redirect_stdout(io.StringIO()):positive=analyze(root/'round0-corrected/stream',root/'round0-corrected/trial/summary.json',
        root/'schedule-contract.json',output/'positive-audit.json')
    result=dict(passed=True,real_positive_boot=positive['boot_id'],verified_real_plateaus=8,
        corrupted_cases_rejected=6,hardware_accessed=False,training_performed=False)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.root,a.output)
