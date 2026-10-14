"""Exercise deferred proof using a synthetic transformation of retained logs.

These fixtures are software tests and never represent a new physical trial.
"""
import argparse
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
from audit_speedloop_full_hall_capture import merge


def run(folder,output):
    folder,output=Path(folder),Path(output);output.mkdir(parents=True,exist_ok=False)
    summary=json.loads((folder/'trial/summary.json').read_text(encoding='utf-8'))
    original=[json.loads(s) for s in (folder/'stream/events.jsonl').read_text(encoding='utf-8').splitlines()]
    summary['hall_read_profile']='pipelined-v1'
    previous=dict(published_count=0,records=[])
    transformed=[]
    for raw in original:
        item=copy.deepcopy(raw)
        if item['kind']=='telemetry':
            current=item['hall_capture']
            item['hall_capture']=dict(published_count=previous['published_count'],records=previous['records'],
                observed_published_count=current['published_count'],read_ms=current['read_ms'],
                confirmation='next-counter-before-commit-v1')
            previous=current
        transformed.append(item)
    def fixture(name,mutator=None):
        root=output/name;(root/'trial').mkdir(parents=True);(root/'stream').mkdir()
        data=copy.deepcopy(transformed)
        if mutator:mutator(data)
        (root/'trial/summary.json').write_text(json.dumps(summary),encoding='utf-8')
        shutil.copyfile(folder/'trial/hall-edges.json',root/'trial/hall-edges.json')
        (root/'stream/events.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in data),encoding='utf-8')
        return root
    positive=fixture('positive-synthetic')
    with redirect_stdout(io.StringIO()):good=merge(positive,positive/'audit')
    assert good['hall_read_profile']=='pipelined-v1'
    def alter(items,key,value):
        event=next(i for i in items if i['kind']=='telemetry' and i['hall_capture']['published_count']>20)
        event['hall_capture'][key]=value
    cases=[('premature-commit','published_count',9999),('counter-reset','observed_published_count',0),
           ('overwrite','observed_published_count',100000),('missing-confirmation','confirmation','none')]
    for name,key,value in cases:
        root=fixture(name,lambda items,k=key,v=value:alter(items,k,v))
        try:
            with redirect_stdout(io.StringIO()):merge(root,root/'audit')
        except ValueError as exc:
            assert 'next-counter proof' in str(exc),str(exc)
        else:raise AssertionError('Forged deferred proof was accepted')
    report=dict(passed=True,synthetic_log_transform=True,hardware_accessed=False,
        new_physical_trial=False,corruption_cases_rejected=len(cases),
        preserved_edge_count=good['total_actual_edges'],exact_tail_overlap=good['halted_tail_overlap_verified'])
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('folder','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.folder,a.output)
