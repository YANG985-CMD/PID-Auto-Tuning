"""Decompose existing Hall error by sector; no inferred physical ground truth."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin


def diagnose(folders, output):
    rows=[];seen=set();hashes={}
    for folder in map(Path,folders):
        score=json.loads((folder/'full-hall-score.json').read_text())
        trial=json.loads((folder/'trial/summary.json').read_text())
        if not score['passed'] or not trial['passed'] or score['boot_id'] in seen:
            raise ValueError('Need distinct successfully stopped physical sessions')
        seen.add(score['boot_id'])
        edges=json.loads((folder/'full-hall-audit/full-hall-edges.json').read_text())['records']
        edges=[e for e in edges if e['model_stage']==4]
        if any(not e['valid'] for e in edges) or any(b['edge']!=a['edge']+1 for a,b in zip(edges,edges[1:])):
            raise ValueError('Invalid or incomplete Hall trace')
        packets=[json.loads(v) for v in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
        origin=capture_origin(packets)
        for plateau in score['plateaus']:
            lo,hi=[origin+t*1000 for t in plateau['score_span_ms']]
            sums=defaultdict(lambda:[0.,0.,0.])
            for a,b in zip(edges,edges[1:]):
                dt=max(0,min(hi,b['t_us'])-max(lo,a['t_us']))
                if dt:
                    error=a['rpm']-1000;s=sums[a['hall_code']]
                    s[0]+=dt;s[1]+=dt*error;s[2]+=dt*error**2
            total=sum(s[0] for s in sums.values())
            if abs(total-(hi-lo))>.01 or len(sums)!=6:raise ValueError('Incomplete scored sectors')
            mse=sum(s[2] for s in sums.values())/total
            means={code:s[1]/s[0] for code,s in sums.items()}
            associated=sum(s[0]*means[code]**2 for code,s in sums.items())/total
            if abs(math.sqrt(mse)-plateau['full_Hall_hold_diagnostic_rmse_rpm'])>1e-8:
                raise ValueError('Diagnostic altered primary score')
            rows.append(dict(boot_id=score['boot_id'],slot=plateau['slot'],kp=plateau['kp'],
                primary_raw_Hall_rmse_rpm=math.sqrt(mse),
                weighted_sector_mean_error_rpm=means,
                sector_associated_mse_fraction=associated/mse,
                within_sector_rmse_rpm=math.sqrt(max(0,mse-associated)),
                causal_six_period_rmse_rpm=plateau['causal_six_interval_diagnostic_rmse_rpm']))
        for name in ('full-hall-score.json','trial/summary.json','full-hall-audit/full-hall-edges.json'):
            path=folder/name;hashes[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
    report=dict(passed=True,plateaus=rows,unique_boots=sorted(seen),
        average_sector_associated_mse_fraction=sum(r['sector_associated_mse_fraction'] for r in rows)/len(rows),
        primary_metric_unchanged=True,hardware_feedback_changed=False,weights_changed=False,
        independent_speed_ground_truth=False,
        interpretation='Sector association can include sensor geometry, commutation torque ripple and true speed ripple; it does not identify a noise floor.',
        deployment_allowed=False,performance_claim_allowed=False,hashes=hashes)
    Path(output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('plateaus','hashes')}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folders',nargs='+',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();diagnose(a.folders,a.output)
