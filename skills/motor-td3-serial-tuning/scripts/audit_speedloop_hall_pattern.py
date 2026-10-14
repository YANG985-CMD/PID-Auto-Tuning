"""Causal Hall diagnostics on stopped logs, without changing primary metrics.

Six intervals use only already occurred edges. Leave-one-boot-out sector
ratios are diagnostics, not calibrated rotor speed or a controller release.
"""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from audit_speedloop_snapshot_timing import snapshot_interval,capture_origin


def inspect_trial(folder):
    folder = Path(folder).resolve()
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    trace = json.loads((folder/'hall-edges.json').read_text(encoding='utf-8'))
    raw = [json.loads(line) for line in (folder/'telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    if not summary['passed'] or summary['final_irq_fault'] or summary['final_tx_fault']:
        raise ValueError('Only successful stopped trial logs are diagnostic inputs')
    edges = trace['records']
    if (len(edges) < 12 or len({p['boot_id'] for p in raw}) != 1
            or any(not e['valid'] or e['model_stage'] != 4 or e['period_us'] <= 0 for e in edges)):
        raise ValueError('Insufficient valid RunStage Hall evidence')
    for a,b in zip(edges,edges[1:]):
        if b['edge'] != a['edge']+1 or b['t_us']-a['t_us'] != b['period_us']:
            raise ValueError('Hall edge gap or timer mismatch')
    derived = []
    origin = summary['trial_timing']['started_us']
    capture_started=capture_origin(raw)
    for index in range(5,len(edges)):
        six = edges[index-5:index+1]
        if len({e['hall_code'] for e in six}) != 6:
            raise ValueError('Six intervals do not cover all Hall sectors')
        current = six[-1]
        ratio = current['period_us']/(sum(e['period_us'] for e in six)/6)
        derived.append(dict(t_us=current['t_us'],elapsed_ms=(current['t_us']-origin)/1000,
            code=current['hall_code'],raw_rpm=current['rpm'],ratio=ratio,
            six_rpm=math.copysign(30000000/sum(e['period_us'] for e in six),current['rpm']),
            six_duration_ms=sum(e['period_us'] for e in six)/1000))
    steady = [e for e in derived if 22400 <= e['elapsed_ms'] <= 23600]
    if len(steady)<100 or set(e['code'] for e in steady)!=set(range(1,7)):
        raise ValueError('Missing common 1000rpm baseline tail')
    ratio = {code:median(e['ratio'] for e in steady if e['code']==code) for code in range(1,7)}
    times = [e['t_us'] for e in derived]
    samples = []
    for packet in raw:
        if not packet['enabled'] or not 22400<=packet['elapsed_ms']<=23600:
            continue
        if packet['speed_ref']!=1000:
            raise ValueError('Common tail is not baseline')
        if packet['kp']!=float_from32(.003389) or packet['ki']!=float_from32(.00144):
            raise ValueError('Common tail gains differ')
        lo,hi = snapshot_interval(packet,capture_started)
        index = bisect.bisect_right(times,lo)-1
        if index != bisect.bisect_right(times,hi)-1:
            raise ValueError('Hall edge lies inside snapshot rounding uncertainty')
        if index<0:
            raise ValueError('No prior six-edge diagnostic')
        edge = derived[index]
        if abs(edge['raw_rpm']-packet['speed'])>1e-4:
            raise ValueError('Hall edge does not match actual telemetry speed')
        snapshot_us=(lo+hi)/2
        samples.append(dict(telemetry_seq=packet['seq'],t_us=packet['t_us'],raw_speed=packet['speed'],
            derived_snapshot_us=snapshot_us,snapshot_uncertainty_us=(hi-lo)/2,
            last_edge_rpm=edge['raw_rpm'],six_rpm=edge['six_rpm'],hall_code=edge['code'],
            causal_edge_age_ms=(snapshot_us-edge['t_us'])/1000,
            six_interval_duration_ms=edge['six_duration_ms']))
    full_edges=0.0;total_us=0
    start,end=origin+22400000,origin+23600000
    for a,b in zip(derived,derived[1:]):
        overlap=max(0,min(end,b['t_us'])-max(start,a['t_us']))
        full_edges+=(a['raw_rpm']-1000)**2*overlap;total_us+=overlap
    if total_us!=1200000:raise ValueError('Full Hall window coverage missing')
    return dict(folder=str(folder),boot_id=raw[0]['boot_id'],ratios=ratio,tail_samples=samples,
        full_Hall_hold_rmse_rpm=math.sqrt(full_edges/total_us),
        telemetry_Hall_sector_counts={code:sum(s['hall_code']==code for s in samples) for code in range(1,7)},
        raw_sha256=hashlib.sha256((folder/'telemetry.jsonl').read_bytes()).hexdigest(),
        hall_sha256=hashlib.sha256((folder/'hall-edges.json').read_bytes()).hexdigest())


def float_from32(x):
    import struct
    return struct.unpack('<f',struct.pack('<f',x))[0]


def run(folders,output):
    output=Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents or output.exists():
        raise ValueError('Use new task temporary output')
    trials=[inspect_trial(folder) for folder in folders]
    if len(trials)<3 or len({t['boot_id'] for t in trials})!=len(trials):
        raise ValueError('Need at least three distinct physical boots')
    result=[]
    for trial in trials:
        others=[t for t in trials if t['boot_id']!=trial['boot_id']]
        crossfit={code:median(t['ratios'][code] for t in others) for code in range(1,7)}
        samples=trial['tail_samples']
        for sample in samples:
            sample['crossfit_sector_diagnostic_rpm']=sample['raw_speed']*crossfit[sample['hall_code']]
        metrics={key:math.sqrt(mean((r[key]-1000)**2 for r in samples))
            for key in ('raw_speed','six_rpm','crossfit_sector_diagnostic_rpm')}
        result.append(dict(boot_id=trial['boot_id'],folder=trial['folder'],samples=len(samples),
            full_Hall_hold_diagnostic_rmse_rpm=trial['full_Hall_hold_rmse_rpm'],
            telemetry_Hall_sector_counts=trial['telemetry_Hall_sector_counts'],
            actual_tail_gain=[.003389,.00144],score_window_ms=[22400,23600],
            tail_rmse_diagnostics_rpm=metrics,
            sector_period_ratios=trial['ratios'],leave_one_boot_out_sector_ratios=crossfit,
            six_interval_mean_span_ms=mean(r['six_interval_duration_ms'] for r in samples),
            maximum_causal_edge_age_ms=max(r['causal_edge_age_ms'] for r in samples),
            telemetry_sha256=trial['raw_sha256'],hall_edges_sha256=trial['hall_sha256']))
    report=dict(source='stopped-real-motor-Hall-period-diagnostic',trials=result,
        timestamp_alignment='Separate elapsed_ms-derived locked capture time; immutable legacy t_us retained',
        holdout_rule='Estimate six sector ratios only from other physical boots; no fitted holdout ratios',
        independent_speed_ground_truth=False,hardware_accessed=False,hardware_feedback_changed=False,
        primary_metric_changed=False,actor_applied=False,deployment_allowed=False,performance_claim_allowed=False,
        limitations='Six-period speed averages real ripple as well as possible Hall geometry bias and adds delay. Sector correction may remove repeatable physical torque ripple; it is not calibrated speed. No counterfactual control response measured.')
    output.mkdir(parents=True)
    (output/'hall-diagnostics.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (output/'causal-samples.json').write_text(json.dumps(trials,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials',nargs='+',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    run(args.trials,args.output)
