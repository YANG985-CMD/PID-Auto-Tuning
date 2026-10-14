"""Predeclared pair-level statistics; individual frames are not replicates."""
import argparse
import json
import math
from pathlib import Path
import statistics
from analyze_speedloop_response import stats
from analyze_speedloop_phases import read_lines


def run(session,output):
    session,out=Path(session).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    contract=json.loads((session/'session-summary.json').read_text(encoding='utf-8'))
    assert contract['passed'] and len(contract['pairs'])==3
    pairs=[];boots=set()
    for dest in sorted(session.glob('pair-*')):
        if not dest.is_dir():continue
        policies={}
        for path in sorted(dest.glob('round-*')):
            run=json.loads((path/'trial/summary.json').read_text(encoding='utf-8'))
            audit=json.loads((path/'audit/analysis.json').read_text(encoding='utf-8'))
            raw=read_lines(path/'trial/telemetry.jsonl')
            assert run['passed'] and audit['passed'] and not run['final_irq_fault'] and not run['final_tx_fault']
            assert raw[0]['boot_id'] not in boots;boots.add(raw[0]['boot_id'])
            lo,hi=audit['raw_stage_proof_t_us']
            active=[r for r in raw if r['enabled']]
            windows={}
            for name,key in [('primary','primary_evaluation_elapsed_ms'),('secondary','secondary_probe_evaluation_elapsed_ms')]:
                start,end=contract[key]
                phase_rows=[r for r in active if start<=r['elapsed_ms']<end]
                assert all(lo<=r['t_us']<=hi for r in phase_rows)
                assert len(phase_rows)>30
                windows[name]=stats(phase_rows)
            policies[run['gain_mode']]=dict(boot_id=raw[0]['boot_id'],windows=windows,
                full_peak_speed_rpm=run['peak_speed_rpm'],nominal_full_peak_current_a=run['nominal_peak_current_a'])
        assert set(policies)=={'baseline','kp_probe'}
        change={}
        for window in ('primary','secondary'):
            a,b=(policies[p]['windows'][window] for p in ('baseline','kp_probe'))
            change[window]=dict(rmse_reduction_percent=100*(1-b['rmse_rpm']/a['rmse_rpm']),
                nominal_peak_current_delta_a=b['nominal_peak_current_a']-a['nominal_peak_current_a'],
                peak_speed_delta_rpm=b['peak_speed_rpm']-a['peak_speed_rpm'])
        pairs.append(dict(pair=dest.name,policies=policies,comparison=change))
    changes=[r['comparison']['primary']['rmse_reduction_percent'] for r in pairs]
    mean=statistics.mean(changes);se=statistics.stdev(changes)/math.sqrt(3)
    t975_df2=.95*math.sqrt(2/(1-.95**2))
    ci=[mean-t975_df2*se,mean+t975_df2*se]
    bcurrent=statistics.mean(r['policies']['baseline']['windows']['primary']['nominal_peak_current_a'] for r in pairs)
    pcurrent=statistics.mean(r['policies']['kp_probe']['windows']['primary']['nominal_peak_current_a'] for r in pairs)
    bspeed=statistics.mean(r['policies']['baseline']['windows']['primary']['peak_speed_rpm'] for r in pairs)
    pspeed=statistics.mean(r['policies']['kp_probe']['windows']['primary']['peak_speed_rpm'] for r in pairs)
    passed=min(changes)>=5 and ci[0]>=5 and pcurrent<=bcurrent and pspeed<=bspeed
    result=dict(schema_version=1,source='real_motor',pairs=pairs,independent_pairs=3,
        primary_rmse_reduction_percent=changes,mean_primary_rmse_reduction_percent=mean,
        mean_reduction_95pct_t_interval=ci,confidence_unit='independent paired trials, df=2; normal-difference assumption',
        nominal_mean_peak_current_a=dict(baseline=bcurrent,kp_probe=pcurrent),
        mean_peak_speed_rpm=dict(baseline=bspeed,kp_probe=pspeed),
        local_probe_repeated_performance_gate_passed=passed,
        actor_tested=False,actor_performance_gate_passed=False,deployment_allowed=False,
        performance_claim_allowed=False,temperature_gate_modified=False)
    out.mkdir(parents=True,exist_ok=True)
    (out/'repeat-analysis.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('primary_rmse_reduction_percent','mean_primary_rmse_reduction_percent','mean_reduction_95pct_t_interval','local_probe_repeated_performance_gate_passed')}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.session,a.output)
