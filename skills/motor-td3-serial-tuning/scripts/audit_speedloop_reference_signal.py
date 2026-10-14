"""Describe measured gain/reward signal; no counterfactual motor claim."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from build_speedloop_fullhall_replay import read, sha


def audit(replay, output):
    replay, output = Path(replay), Path(output)
    assert not output.exists()
    manifest = read(replay/'summary.json')
    assert manifest['passed'] and manifest['reference_data_revision'] == 'reference-excited-local4-capture-v1'
    groups = defaultdict(list)
    penalties = defaultdict(list)
    phase_support = defaultdict(set)
    phase_support_by_boot = defaultdict(set)
    errors = []
    new_boots = {s['boot_id'] for s in manifest['whole_boot_split'] if s['firmware_id'].endswith('v23')}
    for item in manifest['input_manifest']:
        path = Path(item['file'])
        assert sha(path) == item['sha256']
        r = read(path); h = r['full_hall_reward']; span = r['measured_reward_span_us']
        terms = dict(speed=h['mse_rpm2']/1e6,
                     current=.3*(h['peak_nominal_current_a']/2)**2,
                     overspeed=.25*max(0,(h['peak_speed_rpm']-1500)/300)**2,
                     saturation=.25*h['saturation_fraction'])
        reconstructed = -sum(terms.values())*span/100000-.0005*r['physical_delta_action'][0]**2
        errors.append(abs(reconstructed-r['time_scaled_reward']))
        record = dict(boot_id=r['boot_id'],split=r['split'],reference=h['reference_rpm'],
                      kp=r['action_applied'][0],source_kp=r['state']['kp'],duration=span,
                      mse=h['mse_rpm2'],peak_current=h['peak_nominal_current_a'],
                      penalty_rate=sum(terms.values()),terms=terms)
        midpoint_ms=mean(p['elapsed_ms'] for p in (r['response'][0],r['response'][-1]))
        record['in_gain_reference_overlap']=6250<=midpoint_ms<22000
        if r['boot_id'] in new_boots and record['in_gain_reference_overlap']:
            age=(midpoint_ms-6000)%2000
            boundaries=(0,250,750,1250,1750,2000)
            phase=next(i for i in range(5) if boundaries[i]<=age<boundaries[i+1])
            first_age=(r['response'][0]['elapsed_ms']-6000)%2000
            last_age=(r['response'][-1]['elapsed_ms']-6000)%2000
            if boundaries[phase]+30<=first_age<=last_age<=boundaries[phase+1]-30:
                phase_support[(h['reference_rpm'],phase)].add(abs(r['action_applied'][0]-.003389)<1e-9)
                phase_support_by_boot[(r['boot_id'],h['reference_rpm'],phase)].add(abs(r['action_applied'][0]-.003389)<1e-9)
        groups[(r['boot_id'],h['reference_rpm'],r['action_applied'][0])].append(record)
        for key, value in terms.items():
            penalties[key].append(value)
    assert max(errors)<1e-12
    cells=[]
    for (boot, ref, kp), rows in sorted(groups.items()):
        duration=sum(r['duration'] for r in rows)
        cells.append(dict(boot_id=boot,split=rows[0]['split'],reference_rpm=ref,kp=kp,
            rows=len(rows),actual_switch_rows=sum(r['source_kp']!=kp for r in rows),
            response_duration_us=duration,
            time_weighted_raw_Hall_rmse_rpm=math.sqrt(sum(r['mse']*r['duration'] for r in rows)/duration),
            mean_window_peak_nominal_current_a=mean(r['peak_current'] for r in rows),
            penalty_rate_mean=mean(r['penalty_rate'] for r in rows),
            penalty_rate_std=pstdev(r['penalty_rate'] for r in rows)))
    comparisons=[]
    comparison_cells=[]
    for (boot,ref,kp),rows in sorted(groups.items()):
        rows=[r for r in rows if r['in_gain_reference_overlap']]
        if boot not in new_boots or not rows:continue
        duration=sum(r['duration'] for r in rows)
        comparison_cells.append(dict(boot_id=boot,reference_rpm=ref,kp=kp,
            time_weighted_raw_Hall_rmse_rpm=math.sqrt(sum(r['mse']*r['duration'] for r in rows)/duration),
            mean_window_peak_nominal_current_a=mean(r['peak_current'] for r in rows)))
    for boot in sorted(new_boots):
        for ref in (950,1000,1050):
            subset=[r for r in comparison_cells if r['boot_id']==boot and r['reference_rpm']==ref]
            baseline=next(r for r in subset if abs(r['kp']-.003389)<1e-9)
            for r in subset:
                if r is baseline:continue
                comparisons.append(dict(boot_id=boot,reference_rpm=ref,kp=r['kp'],
                    descriptive_RMSE_change_pct=100*(baseline['time_weighted_raw_Hall_rmse_rpm']-r['time_weighted_raw_Hall_rmse_rpm'])/baseline['time_weighted_raw_Hall_rmse_rpm'],
                    descriptive_peak_current_mean_change_a=r['mean_window_peak_nominal_current_a']-baseline['mean_window_peak_nominal_current_a'],
                    independently_controlled_performance_trial=False))
    report=dict(passed=True,unique_windows=manifest['total_unique_windows'],
        reward_reconstruction_max_error=max(errors),
        penalty_rate_mean={k:mean(v) for k,v in penalties.items()},
        penalty_rate_std={k:pstdev(v) for k,v in penalties.items()},
        reference_phase_support=[dict(reference_rpm=ref,phase_bin_ms=(0,250,750,1250,1750,2000)[phase:phase+2],
            baseline_and_probe_both_observed=len(values)==2,baseline_present=True in values,probe_present=False in values)
            for (ref,phase),values in sorted(phase_support.items())],
        reference_phase_cells_with_baseline_probe_overlap=sum(len(v)==2 for v in phase_support.values()),
        reference_phase_cells_total=len(phase_support),
        baseline_probe_phase_overlap_by_boot=[dict(boot_id=boot,
            covered_cells=sum(len(values)==2 for (b,ref,phase),values in phase_support_by_boot.items() if b==boot),
            total_cells=sum(b==boot for b,ref,phase in phase_support_by_boot)) for boot in sorted(new_boots)],
        phase_support_uses_complete_response_with_30ms_boundary_margin=True,
        boot_reference_gain_cells=cells,new_reference_boot_descriptive_comparisons=comparisons,
        switches_and_holds_not_independent_replicates=True,
        action_context_and_time_confounding_not_removed=True,
        nominal_current_not_independently_calibrated=True,
        reference_steps_may_leave_transient_response=True,
        observed_gain_group_association_is_not_causal_effect=True,
        source_manifest_sha256=sha(replay/'summary.json'),hardware_accessed=False,
        training_performed=False,physical_rewards_unchanged=True,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('boot_reference_gain_cells','new_reference_boot_descriptive_comparisons')}))
    print(json.dumps(comparisons))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();audit(args.replay,args.output)
