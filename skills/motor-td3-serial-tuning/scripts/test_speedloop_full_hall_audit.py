"""Audit full real edge history; reject missing or inconsistent readback."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
from audit_speedloop_full_hall_capture import merge

def run(folder,output):
    folder,output=Path(folder),Path(output);output.mkdir(parents=True,exist_ok=False)
    def mutation_case(name,mutator,reason):
        scratch=output/name;shutil.copytree(folder,scratch);mutator(scratch)
        try:
            with redirect_stdout(io.StringIO()):merge(scratch,scratch/'audit')
        except ValueError as e:
            assert reason in str(e),(name,str(e));return
        raise AssertionError('Corruption admitted: '+name)
    def event_change(scratch,fn):
        p=scratch/'stream/events.jsonl';items=[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()]
        fn(items);p.write_text(''.join(json.dumps(i)+'\n' for i in items),encoding='utf-8')
    def missing_edge(scratch):
        def change(items):
            event=next(i for i in items if i['kind']=='telemetry' and i['hall_capture']['records'])
            event['hall_capture']['records'].pop()
        event_change(scratch,change)
    mutation_case('missing-published-edge',missing_edge,'Live Hall gap')
    def wrong_overlap(scratch):
        p=scratch/'trial/hall-edges.json';r=json.loads(p.read_text(encoding='utf-8'))
        r['records'][0]['rpm']+=1;p.write_text(json.dumps(r),encoding='utf-8')
    mutation_case('changed-tail-readback',wrong_overlap,'differs from actual halted')
    def changed_boot(scratch):
        def change(items):
            event=next(i for i in items if i['kind']=='telemetry' and i['packet']['seq']>50)
            event['packet']['boot_id']='not-the-real-boot'
        event_change(scratch,change)
    mutation_case('mixed-boot',changed_boot,'Mixed physical boots')
    def unconfirmed_stop(scratch):
        p=scratch/'trial/summary.json';r=json.loads(p.read_text(encoding='utf-8'))
        r['protocol_stop_acknowledged']=False;p.write_text(json.dumps(r),encoding='utf-8')
    mutation_case('unconfirmed-stop',unconfirmed_stop,'complete stopped physical trial')
    with redirect_stdout(io.StringIO()):positive=merge(folder,output/'positive')
    result=dict(passed=True,corruption_cases_rejected=4,total_real_edges=positive['total_actual_edges'],
        exact_halted_overlap=positive['halted_tail_overlap_verified'],hardware_accessed=False)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('folder','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.folder,a.output)
