"""Audit late-phase physical response; two rounds never prove improvement."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from analyze_speedloop_phases import read_lines,metrics


def stats(rows):
    r=metrics(rows)
    if not r:return None
    x=[t['elapsed_ms']/1000 for t in rows];y=[t['speed'] for t in rows]
    xm,ym=statistics.mean(x),statistics.mean(y)
    d=sum((t-xm)**2 for t in x)
    r.update(mean_speed_rpm=ym,speed_std_rpm=statistics.pstdev(y),
             span_ms=rows[-1]['elapsed_ms']-rows[0]['elapsed_ms'],
             fitted_trend_rpm_per_s=sum((a-xm)*(b-ym) for a,b in zip(x,y))/d if d else None)
    return r


def run(batch,output):
    batch,out=Path(batch).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    collection=json.loads((batch/'collection-summary.json').read_text(encoding='utf-8'))
    assert collection['passed'] and len(collection['rounds'])==2
    results=[];boots=set()
    for dest in sorted(batch.glob('round-*')):
        report=json.loads((dest/'trial/summary.json').read_text(encoding='utf-8'))
        audit=json.loads((dest/'audit/analysis.json').read_text(encoding='utf-8'))
        assert report['passed'] and audit['passed'] and report['final_irq_fault']==report['final_tx_fault']==0
        raw=read_lines(dest/'trial/telemetry.jsonl');active=[r for r in raw if r['enabled']]
        boot=raw[0]['boot_id'];assert boot not in boots;boots.add(boot)
        lo,hi=audit['raw_stage_proof_t_us']
        rows=[r for r in active if lo<=r['t_us']<=hi]
        phases={}
        for name,start,end in [('pre_probe',4000,5000),('probe_time',5000,6000),
                               ('recovery',6000,7800),('late_tail',6500,7800)]:
            phase=[r for r in rows if start<=r['elapsed_ms']<end]
            phases[name]=stats(phase)
        probe=[r for r in rows if r['kp']>.0034]
        changes=[]
        for prev,r in zip(active,active[1:]):
            if (prev['kp'],prev['ki'])!=(r['kp'],r['ki']):
                changes.append(dict(command_seq=r['applied_seq'],t_apply_us=r['t_apply_us'],
                    elapsed_ms=(r['t_apply_us']-report['trial_timing']['started_us'])/1000,
                    actual_kp=r['kp'],actual_ki=r['ki']))
        edges=json.loads((dest/'trial/hall-edges.json').read_text(encoding='utf-8'))['records']
        hall=[]
        for i in range(5,len(edges)):
            six=edges[i-5:i+1]
            if not all(e['valid'] and e['model_stage']==4 and e['period_us']>0 for e in six):continue
            t=(edges[i]['t_us']-report['trial_timing']['started_us'])/1000
            if t>=6500:
                hall.append(30000000/sum(e['period_us'] for e in six))
        results.append(dict(round=dest.name,boot_id=boot,gain_mode=report['gain_mode'],
            run_entry_elapsed_ms=(report['trial_timing']['run_started_us']-report['trial_timing']['started_us'])/1000,
            proven_closed_loop_span_ms=(hi-lo)/1000,phases=phases,
            actual_probe_metrics=stats(probe),actual_gain_changes=changes,
            late_tail_six_period_hall_diagnostic=dict(samples=len(hall),mean_rpm=statistics.mean(hall),
                rmse_rpm=math.sqrt(statistics.mean((v-1000)**2 for v in hall))),
            six_period_metric_is_independent_encoder=False,
            full_trial_peak_speed_rpm=report['peak_speed_rpm'],
            nominal_full_trial_peak_current_a=report['nominal_peak_current_a'],
            raw_telemetry_sha256=hashlib.sha256((dest/'trial/telemetry.jsonl').read_bytes()).hexdigest(),
            audit_candidate_windows=audit['raw_stage_confirmed_candidates']))
    out.mkdir(parents=True,exist_ok=True)
    result=dict(schema_version=1,source='real_motor',analysis_hardware_accessed=False,rounds=results,
        total_motion_ms=sum(r['actual_motion_ms'] for r in collection['rounds']),
        duration_choice_seconds=8,candidate_admission_passed=False,ordinary_deployment_allowed=False,
        performance_claim_allowed=False,temperature_gate_modified=False,
        interpretation='One baseline and one local probe; causal action evidence, insufficient independent repetitions for performance admission')
    (out/'response-analysis.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result,allow_nan=False));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.batch,a.output)
