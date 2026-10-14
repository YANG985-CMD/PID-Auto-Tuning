"""Separate startup, closed-loop entry transient and observation duration.

Reads already-audited physical logs only. A duration gate is an evidence-quality
requirement, not a physical safety approval or a learned-policy performance test.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def read_lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def metrics(rows):
    if not rows:return None
    return {'samples':len(rows),'rmse_rpm':math.sqrt(statistics.mean(
        (r['speed_ref']-r['speed'])**2 for r in rows)),
        'peak_speed_rpm':max(abs(r['speed']) for r in rows),
        'nominal_peak_current_a':max(abs(r['current']) for r in rows)}


def analyze_round(path):
    summary=json.loads((path/'trial/summary.json').read_text(encoding='utf-8'))
    audit=json.loads((path/'audit/analysis.json').read_text(encoding='utf-8'))
    if not summary['passed'] or not audit['passed']:raise ValueError('Failed physical/audit record')
    data=read_lines(path/'trial/telemetry.jsonl')
    active=[r for r in data if r['enabled']]
    edges=json.loads((path/'trial/hall-edges.json').read_text(encoding='utf-8'))['records']
    first=next(i for i,e in enumerate(edges) if e['model_stage']==4)
    if not all(e['valid'] and e['model_stage']==4 for e in edges[first:]):
        raise ValueError('Closed-loop proof is discontinuous')
    start,end=edges[first]['t_us'],edges[-1]['t_us']
    stage=[r for r in active if start<=r['t_us']<=end]
    if not stage:raise ValueError('Missing stage-confirmed telemetry')
    origin=active[-1]['t_us']-round(active[-1]['elapsed_ms']*1000)
    timing=summary.get('trial_timing')
    if timing:
        if not timing['run_seen'] or timing['fault']:raise ValueError('Bad MCU stage clock')
        run_start=timing['run_started_us']
        basis='MCU generated stage 4, latched by 1ms tick'
    elif first>0 and edges[first-1]['model_stage']!=4:
        run_start=start
        basis='first retained stage-4 Hall edge; entry is an upper bound'
    else:
        run_start=start
        basis='retained stage-4 ring only; actual entry is unknown'
    coverage=(stage[-1]['t_us']-start)/1000
    evaluation=[r for r in stage if r['t_us']-run_start>=800000]
    evaluation_span=(evaluation[-1]['t_us']-evaluation[0]['t_us'])/1000 if len(evaluation)>1 else 0
    # Fixed diagnostic specification: at least 2s proven closed-loop span and
    # at least 1s after excluding the first 0.8s. Does not assert settling.
    adequate=coverage>=2000 and evaluation_span>=1000
    probe=[r for r in stage if r['kp']>.0034]
    initial=[r for r in stage if r['elapsed_ms']<2400]
    tail=[r for r in stage if r['elapsed_ms']>=2500]
    return {'round':path.name,'boot_id':data[0]['boot_id'],
        'policy':summary.get('comparison_policy',summary['gain_mode']),
        'run_entry_elapsed_ms':(run_start-origin)/1000,'run_entry_basis':basis,
        'proven_closed_loop_span_ms':coverage,'closed_loop_last_elapsed_ms':stage[-1]['elapsed_ms'],
        'first_proven_stage_sample_speed_rpm':stage[0]['speed'],
        'hall_stage_transition_retained':first>0 and edges[first-1]['model_stage']!=4,
        'closed_loop_metrics':metrics(stage),'entry_before_2400ms_metrics':metrics(initial),
        'tail_from_2500ms_metrics':metrics(tail),'actual_probe_metrics':metrics(probe),
        'evaluation_after_800ms_metrics':metrics(evaluation),
        'evaluation_after_800ms_span_ms':evaluation_span,
        'duration_evidence_sufficient':adequate,'steady_state_proven':False,
        'all_faults_zero':all(r['fault']==0 for r in data),
        'stop_acknowledged':summary['protocol_stop_acknowledged'],
        'physical_shutdown_verified':audit['stop_and_physical_shutdown_verified'],
        'raw_telemetry_sha256':hashlib.sha256((path/'trial/telemetry.jsonl').read_bytes()).hexdigest()}


def run(batch,output,requested_rounds=6):
    if not 1<=requested_rounds<=6:raise ValueError('Expected one to six rounds')
    output=Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents:
        raise ValueError('Analysis output must use the task temporary root')
    output.mkdir(parents=True,exist_ok=True)
    rounds=[analyze_round(p) for p in sorted(Path(batch).glob('round-*'))
            if (p/'audit/analysis.json').exists()]
    if len({r['boot_id'] for r in rounds})!=len(rounds):raise ValueError('Duplicate boot session')
    report={'schema_version':1,'source':'real_motor','analysis_hardware_accessed':False,
        'completed_audited_rounds':len(rounds),'requested_rounds':requested_rounds,
        'batch_completed':len(rounds)==requested_rounds,'missing_rounds_not_automatically_retried':True,
        'duration_specification':{'minimum_proven_closed_loop_ms':2000,
            'exclude_entry_transient_ms':800,'minimum_evaluation_span_ms':1000,
            'settling_assumed':False,'physical_approval':False},
        'ordinary_deployment_allowed':False,'performance_claim_allowed':False,
        'td3_training_performed':False,'temperature_gate_modified':False,'rounds':rounds}
    (output/'phase-analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'rounds':len(rounds),'duration_evidence_passed':sum(r['duration_evidence_sufficient'] for r in rounds),
        'closed_loop_span_ms':[round(r['proven_closed_loop_span_ms'],3) for r in rounds]},allow_nan=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--requested-rounds',type=int,default=6)
    args=parser.parse_args();run(args.batch,args.output,args.requested_rounds)
