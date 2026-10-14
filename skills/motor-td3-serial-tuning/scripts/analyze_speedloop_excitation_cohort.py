"""Predeclared reference-step metrics; pairs, not frames, are replicates."""
import argparse
import json
import math
from pathlib import Path
import statistics
from analyze_speedloop_phases import metrics
from prepare_speedloop_excitation_replay import verified_round
from speedloop_response_windows import write


def run(session,output):
    session,out=Path(session).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    contract=json.loads((session/'session-summary.json').read_text(encoding='utf-8'))
    if not contract['passed'] or len(contract['pairs'])!=3:raise ValueError('Incomplete finite cohort')
    boots=set();hashes=set();pairs=[]
    for pair in range(1,4):
        modes={}
        for path in sorted((session/f'pair-{pair:02d}').glob('round-*')):
            trial,audit,raw,boot,digest=verified_round(path,boots,hashes)
            active=[r for r in raw if r['enabled']];lo,hi=audit['raw_stage_proof_t_us']
            windows={}
            intervals=[('primary',contract['primary_evaluation_elapsed_ms'])]
            intervals.extend((f'step-{i+1}',v) for i,v in enumerate(contract['secondary_intervals_elapsed_ms']))
            for name,(start,end) in intervals:
                selected=[r for r in active if start<=r['elapsed_ms']<end]
                if len(selected)<30 or not all(lo<=r['t_us']<=hi for r in selected):
                    raise ValueError('Evaluation is missing raw stage proof')
                windows[name]=metrics(selected)
            modes[trial['gain_mode']]=dict(boot_id=boot,windows=windows,
                full_trial_peak_speed_rpm=trial['peak_speed_rpm'],
                nominal_full_trial_peak_current_a=trial['nominal_peak_current_a'],
                raw_telemetry_sha256=digest)
        if set(modes)!={'baseline','kp_probe'}:raise ValueError('Missing paired controller')
        comparisons={}
        for name in modes['baseline']['windows']:
            a=modes['baseline']['windows'][name];b=modes['kp_probe']['windows'][name]
            comparisons[name]=dict(rmse_reduction_percent=100*(1-b['rmse_rpm']/a['rmse_rpm']),
                nominal_peak_current_delta_a=b['nominal_peak_current_a']-a['nominal_peak_current_a'],
                peak_speed_delta_rpm=b['peak_speed_rpm']-a['peak_speed_rpm'])
        pairs.append(dict(pair=pair,validation_split=pair in contract['new_validation_pairs'],
                          policies=modes,comparison=comparisons))
    changes=[p['comparison']['primary']['rmse_reduction_percent'] for p in pairs]
    mean=statistics.mean(changes);se=statistics.stdev(changes)/math.sqrt(3)
    t975=.95*math.sqrt(2/(1-.95**2));ci=[mean-t975*se,mean+t975*se]
    currents={m:statistics.mean(p['policies'][m]['windows']['primary']['nominal_peak_current_a'] for p in pairs)
              for m in ('baseline','kp_probe')}
    speeds={m:statistics.mean(p['policies'][m]['windows']['primary']['peak_speed_rpm'] for p in pairs)
            for m in ('baseline','kp_probe')}
    passed=min(changes)>=5 and ci[0]>=5 and currents['kp_probe']<=currents['baseline'] and speeds['kp_probe']<=speeds['baseline']
    result=dict(schema_version=1,source='real_motor',pairs=pairs,independent_pairs=3,
        primary_rmse_reduction_percent=changes,mean_primary_rmse_reduction_percent=mean,
        mean_reduction_95pct_t_interval=ci,confidence_unit='independent pairs, df2; normal-difference assumption',
        nominal_mean_peak_current_a=currents,mean_peak_speed_rpm=speeds,
        local_probe_repeated_performance_gate_passed=passed,actor_tested=False,
        actor_performance_gate_passed=False,deployment_allowed=False,performance_claim_allowed=False,
        temperature_gate_modified=False)
    write(out/'excitation-analysis.json',result)
    print(json.dumps({k:result[k] for k in ('primary_rmse_reduction_percent','mean_primary_rmse_reduction_percent','mean_reduction_95pct_t_interval','local_probe_repeated_performance_gate_passed')}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('session','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.session,a.output)
