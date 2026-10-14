"""Nominal PI action scale versus telemetry code spacing, using real records.

The incremental PI output is a same-error-history algebraic estimate, not a
measured counterfactual motor current. Neither protection nor score is changed.
"""
import argparse,bisect,hashlib,json,math
from pathlib import Path

read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
NOMINAL_STEP_A=.02197265625

def nominal_increment(delta_kp,error,application_error):
    return delta_kp*(error-application_error)

def audit(replay,firmware,output):
    replay,firmware,output=map(Path,(replay,firmware,output))
    if output.exists():raise ValueError('One-use output required')
    master=read(replay/'summary.json');assert master['passed']
    assert len(master['input_manifest'])==master['total_unique_windows']
    pi=firmware/'private-copy/codex-pi/motor_td3_speedloop_pi.c'
    model=firmware/'private-copy/MATLAB/FOC_Model.c'
    code=pi.read_text();modelcode=model.read_text()
    assert 'next_i=*integral+(*kp-s->pending_kp)*error;' in code
    assert 'spd_kpki.spd_kp * rtb_IntegralGain + Integrator' in modelcode
    folders={b['boot_id']:Path(b['raw_folder']) for b in master['whole_boot_split']}
    splits={b['boot_id']:b['split'] for b in master['whole_boot_split']}
    assert len(folders)==len(master['whole_boot_split'])
    full={};HallHash={};spacing=[];sources=[];keys=set()
    for boot,folder in folders.items():
        path=folder/'full-hall-audit/full-hall-edges.json';h=read(path)
        assert h['boot_id']==boot and h['full_session_history']
        full[boot]=[e for e in h['records'] if e['model_stage']==4]
        HallHash[boot]=sha(path)
        assert all(e['valid'] and math.isfinite(e['rpm']) for e in full[boot])
        assert all(a['t_us']<b['t_us'] for a,b in zip(full[boot],full[boot][1:]))
        packets=folder/'trial/telemetry.jsonl';trace=[json.loads(line) for line in packets.read_text().splitlines()]
        spacing.extend(abs(p['current']/NOMINAL_STEP_A-round(p['current']/NOMINAL_STEP_A)) for p in trace)
        sources.append(dict(boot_id=boot,Hall_sha256=sha(path),telemetry_sha256=sha(packets)))
    rows=[];costSensitivity=[]
    for item in master['input_manifest']:
        assert sha(item['file'])==item['sha256'];w=read(item['file']);h=w['full_hall_reward']
        assert sha(item['raw_window_file'])==item['raw_window_sha256']==w['raw_window_sha256']
        assert HallHash[w['boot_id']]==h['full_hall_sha256']
        assert w['split']==item['split']==splits[w['boot_id']]
        assert item['physical_key']==w['physical_key'] and w['physical_key'] not in keys
        keys.add(w['physical_key'])
        current=h['peak_nominal_current_a'];nominalCurrentOneCodeCost=.3/4*((current+NOMINAL_STEP_A)**2-current**2)
        desiredFivePercentSpeedCost=.0975*h['mse_rpm2']/1e6
        costSensitivity.append(nominalCurrentOneCodeCost/max(desiredFivePercentSpeedCost,1e-12))
        delta=w['action_applied'][0]-w['state']['kp']
        if delta==0:continue
        edges=full[w['boot_id']];times=[e['t_us'] for e in edges]
        at=bisect.bisect_right(times,w['t_effective_us'])-1
        if at<0:raise ValueError('Missing pre-application Hall record')
        reference=w['state']['speed_ref'];anchor=reference-edges[at]['rpm']
        sourceAnchor=reference-w['state']['speed']
        total=squared=sourceSquared=0.;peak=0.
        for a,b in zip(h['records'],h['records'][1:]):
            if b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us'] or not a['valid'] or not b['valid'] or a['model_stage']!=4:
                raise ValueError('Broken response Hall evidence')
            width=max(0,min(h['end_us'],b['t_us'])-max(h['begin_us'],a['t_us']))
            value=nominal_increment(delta,reference-a['rpm'],anchor)
            sourceValue=nominal_increment(delta,reference-a['rpm'],sourceAnchor)
            total+=width;squared+=width*value**2;sourceSquared+=width*sourceValue**2
            if width:peak=max(peak,abs(value))
        assert total==w['measured_reward_span_us']
        rms=math.sqrt(squared/total);sourceRms=math.sqrt(sourceSquared/total)
        rows.append(dict(physical_key=item['physical_key'],split=item['split'],boot_id=w['boot_id'],
            source_kp=w['state']['kp'],actual_target_kp=w['action_applied'][0],delta_kp=delta,
            nominal_same_error_history_Iq_increment_RMS_a=rms,
            source_telemetry_anchor_increment_RMS_a=sourceRms,
            nominal_same_error_history_increment_peak_a=peak,
            both_anchor_RMS_below_one_nominal_telemetry_code=max(rms,sourceRms)<NOMINAL_STEP_A,
            nominal_current_one_code_cost_over_5percent_RMSE_cost=nominalCurrentOneCodeCost/max(desiredFivePercentSpeedCost,1e-12)))
    assert rows
    rms=sorted(r['nominal_same_error_history_Iq_increment_RMS_a'] for r in rows)
    sensitivity=sorted(costSensitivity)
    report=dict(passed=True,source_replay_sha256=sha(replay/'summary.json'),sources=sources,rows=rows,
        original_window_and_full_Hall_hashes_verified=True,unique_windows=len(keys),
        switch_windows=len(rows),nominal_current_telemetry_code_step_a=NOMINAL_STEP_A,
        maximum_observed_integer_code_residual=max(spacing),all_currents_align_to_nominal_step=max(spacing)<1e-5,
        nominal_increment_RMS_quartile_median_p90_a=[rms[int((len(rms)-1)*p)] for p in (.25,.5,.9)],
        both_anchors_below_one_code_fraction=sum(r['both_anchor_RMS_below_one_nominal_telemetry_code'] for r in rows)/len(rows),
        one_nominal_current_code_cost_over_5percent_speed_cost_median=sensitivity[len(sensitivity)//2],
        algebraic_formula='delta_Iq_estimate = delta_Kp * (error(t) - error_at_application_estimate)',
        application_error_not_directly_recorded=True,error_anchor_estimated_from_Hall=True,
        estimate_is_not_measured_motor_or_counterfactual_current=True,
        nominal_scale_is_not_independent_current_calibration=True,
        current_protection_or_reward_or_metric_changed=False,firmware_written=False,
        firmware_PI_source_sha256=sha(pi),generated_model_source_sha256=sha(model),
        hardware_accessed=False,training_performed=False,actor_applied=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','sources')}));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('replay','firmware','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();audit(a.replay,a.firmware,a.output)
