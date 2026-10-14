"""Compare sparse telemetry with all retained causal Hall intervals.

Diagnostic only: Hall estimators are not independent speed ground truth.
Retained edge ring coverage is checked; uncovered plateaus are not reconstructed.
"""
import argparse
import bisect
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin,snapshot_interval
from speedloop_response_windows import temporal_mean

def audit(trial,analysis,output,full_hall=None):
    trial,analysis,output=map(Path,(trial,analysis,output))
    summary=json.loads((trial/'summary.json').read_text(encoding='utf-8'))
    score=json.loads(analysis.read_text(encoding='utf-8'))
    edge_path=Path(full_hall) if full_hall else trial/'hall-edges.json'
    all_edges=json.loads(edge_path.read_text(encoding='utf-8'))['records']
    edges=[e for e in all_edges if e['model_stage']==4]
    packets=[json.loads(line) for line in (trial/'telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    if not summary['passed'] or summary['final_irq_fault'] or summary['final_tx_fault']:
        raise ValueError('Need successful stopped trial evidence')
    if any(not e['valid'] or e['model_stage']!=4 or e['period_us']<=0 for e in edges):raise ValueError('Invalid Hall evidence')
    if any(b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us'] for a,b in zip(edges,edges[1:])):
        raise ValueError('Hall edge gap or clock mismatch')
    origin=capture_origin(packets);times=[e['t_us'] for e in edges];mismatches=0;certain=0;ambiguous=0;aligned={}
    six={i:math.copysign(30000000/sum(e['period_us'] for e in edges[i-5:i+1]),edges[i]['rpm'])
        for i in range(5,len(edges)) if len({e['hall_code'] for e in edges[i-5:i+1]})==6}
    for p in packets:
        if not p['enabled'] or p['t_us']<times[5] or p['t_us']>=times[-1]:continue
        lo,hi=snapshot_interval(p,origin);a=bisect.bisect_right(times,lo)-1;b=bisect.bisect_right(times,hi)-1
        if a!=b:ambiguous+=1;continue
        certain+=1
        if abs(p['speed']-edges[a]['rpm'])>1e-4:mismatches+=1
        aligned[p['seq']]=a
    if mismatches:raise ValueError('Actual telemetry does not match retained causal Hall edge')
    rows=[]
    for s in score['plateaus']:
        # Align elapsed_ms with actual BEGIN application, not the later trial hook.
        lo=origin+s['analysis_start_ms']*1000
        hi=origin+s['analysis_end_ms']*1000
        if lo<times[5] or hi>times[-1]:
            rows.append(dict(slot=s['slot'],full_Hall_covered=False,reason='Ring retains tail only'));continue
        selected=[p for p in packets if s['first_seq']<=p['seq']<=s['last_seq']]
        counts=Counter(edges[aligned[p['seq']]]['hall_code'] for p in selected if p['seq'] in aligned)
        totals=Counter();raw_error=six_error=0.;covered=0.;full_peak=0.
        for i,(a,b) in enumerate(zip(edges,edges[1:])):
            overlap=max(0,min(hi,b['t_us'])-max(lo,a['t_us']))
            if not overlap:continue
            if i not in six:raise ValueError('Six-edge coverage missing')
            raw_error+=(a['rpm']-1000)**2*overlap;six_error+=(six[i]-1000)**2*overlap
            totals[a['hall_code']]+=overlap;covered+=overlap;full_peak=max(full_peak,abs(a['rpm']))
        if abs(covered-(hi-lo))>.01:raise ValueError('Incomplete full-Hall scored span')
        rows.append(dict(slot=s['slot'],kp=s['kp'],ki=s['ki'],full_Hall_covered=True,
            score_span_ms=[s['analysis_start_ms'],s['analysis_end_ms']],packet_count=len(selected),
            certain_packet_alignment=sum(counts.values()),telemetry_sector_counts=dict(counts),
            full_Hall_sector_occupancy_fraction={c:totals[c]/covered for c in range(1,7)},
            primary_telemetry_rmse_rpm=s['rmse_rpm'],full_Hall_hold_diagnostic_rmse_rpm=math.sqrt(raw_error/covered),
            causal_six_interval_diagnostic_rmse_rpm=math.sqrt(six_error/covered),full_Hall_peak_speed_rpm=full_peak))
    result=dict(passed=True,boot_id=score['boot_id'],matched_packets=certain,ambiguous_packets=ambiguous,
        mismatched_packets=mismatches,retained_Hall_span_ms=[(times[0]-summary['trial_timing']['started_us'])/1000,
            (times[-1]-summary['trial_timing']['started_us'])/1000],plateaus=rows,
        independent_speed_ground_truth=False,
        primary_metric_changed=summary.get('primary_metric_version')=='raw-Hall-held-time-integral-v1',
        declared_primary_metric_version=summary.get('primary_metric_version','legacy-sparse-telemetry'),
        legacy_telemetry_statistics_retained=True,hardware_feedback_changed=False,
        training_performed=False,actor_applied=False,deployment_allowed=False,performance_claim_allowed=False,
        limitations='Averaging may remove physical ripple as well as Hall geometry bias; no counterfactual response.',
        metric_version='raw-Hall-held-time-integral-v1',clock_origin='actual BEGIN application',
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (edge_path,trial/'telemetry.jsonl',analysis)})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('trial','analysis','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--full-hall')
    a=p.parse_args();audit(a.trial,a.analysis,a.output,a.full_hall)
