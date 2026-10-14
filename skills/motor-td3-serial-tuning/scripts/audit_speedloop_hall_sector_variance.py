"""Decompose retained Hall error without changing feedback or acceptance metric.

Sector association can include both sensor geometry and physical ripple. It is
not an independent rotor-speed measurement or a corrected performance score.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin


def audit(folder,output):
    folder,output=Path(folder),Path(output)
    scores=json.loads((folder/'full-hall-score.json').read_text(encoding='utf-8'))
    plateaus=json.loads((folder/'plateaus.json').read_text(encoding='utf-8'))
    trace=json.loads((folder/'full-hall-audit/full-hall-edges.json').read_text(encoding='utf-8'))
    packets=[json.loads(s) for s in (folder/'trial/telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    origin=capture_origin(packets);edges=[r for r in trace['records'] if r['model_stage']==4]
    groups=defaultdict(lambda:defaultdict(lambda:[0.,0.,0.]))
    byslot={r['slot']:r for r in plateaus['plateaus']}
    for row in scores['plateaus']:
        if not row['full_Hall_covered']:raise ValueError('Incomplete scored Hall span')
        lo,hi=[origin+t*1000 for t in row['score_span_ms']]
        total=weighted_error2=0.
        for a,b in zip(edges,edges[1:]):
            width=max(0.,min(hi,b['t_us'])-max(lo,a['t_us']))
            if not width:continue
            error=a['rpm']-1000.;v=groups[str(byslot[row['slot']]['level'])][str(a['hall_code'])]
            v[0]+=width;v[1]+=width*error;v[2]+=width*error*error
            total+=width;weighted_error2+=width*error*error
        if abs(total-(hi-lo))>.01 or abs(math.sqrt(weighted_error2/total)-row['full_Hall_hold_diagnostic_rmse_rpm'])>1e-8:
            raise ValueError('Decomposition differs from predeclared full-Hall metric')
    metrics={}
    for level,sectors in groups.items():
        if set(sectors)!=set(map(str,range(1,7))):raise ValueError('Incomplete Hall sector coverage')
        weight=sum(v[0] for v in sectors.values());mean=sum(v[1] for v in sectors.values())/weight
        mse=sum(v[2] for v in sectors.values())/weight
        between=sum(v[0]*(v[1]/v[0]-mean)**2 for v in sectors.values())/weight
        within=sum(v[2]-v[1]**2/v[0] for v in sectors.values())/weight
        if abs(mse-mean*mean-between-within)>1e-7:raise ValueError('Variance identity failed')
        metrics[level]=dict(full_hall_rmse_rpm=math.sqrt(mse),mean_error_rpm=mean,
            sector_associated_mse_fraction=between/mse,within_sector_mse_fraction=within/mse,
            mean_bias_mse_fraction=mean*mean/mse,
            sector_mean_error_rpm={k:v[1]/v[0] for k,v in sectors.items()})
    result=dict(passed=True,boot_id=scores['boot_id'],metrics=metrics,
        independent_speed_ground_truth=False,feedback_or_primary_metric_changed=False,
        hardware_accessed=False,training_performed=False,deployment_allowed=False,
        interpretation='Sector association alone cannot distinguish Hall geometry from physical speed ripple',
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (folder/'full-hall-score.json',folder/'full-hall-audit/full-hall-edges.json')})
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('folder','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();audit(a.folder,a.output)
