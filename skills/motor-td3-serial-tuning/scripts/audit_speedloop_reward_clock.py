"""Compare guard-clock rewards with conservatively bounded sensor snapshots."""
import argparse
import bisect
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from audit_speedloop_snapshot_timing import capture_origin,snapshot_interval


def integrate(edges,times,lo,hi):
    start=bisect.bisect_right(times,lo)-1;end=bisect.bisect_left(times,hi)
    if start<0 or end>=len(edges) or not hi>lo:raise ValueError('Incomplete Hall interval')
    total=mse=0.;peak=0.
    for a,b in zip(edges[start:end],edges[start+1:end+1]):
        if not a['valid'] or b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us']:
            raise ValueError('Hall gap')
        dt=max(0,min(hi,b['t_us'])-max(lo,a['t_us']))
        total+=dt;mse+=dt*(a['rpm']-1000)**2
        if dt:peak=max(peak,abs(a['rpm']))
    if abs(total-(hi-lo))>1e-7:raise ValueError('Reward coverage gap')
    return dict(duration_us=total,mse_rpm2=mse/total,peak_speed_rpm=peak)


def audit(replay,output):
    replay=Path(replay);source_path=replay/'summary.json';source=json.loads(source_path.read_text())
    assert source['passed'] and source['split_frozen_before_gradients']
    cache={};rows=[];groups=defaultdict(list)
    for item in source['input_manifest']:
        path=Path(item['file']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        w=json.loads(path.read_text());folder=Path(item['raw_window_file']).parent.parent
        if folder not in cache:
            packets=[json.loads(v) for v in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
            hall=folder/'full-hall-audit/full-hall-edges.json'
            assert hashlib.sha256(hall.read_bytes()).hexdigest()==w['full_hall_reward']['full_hall_sha256']
            edges=json.loads(hall.read_text())['records'];edges=[e for e in edges if e['model_stage']==4]
            cache[folder]=(capture_origin(packets),edges,[e['t_us'] for e in edges])
        origin,edges,times=cache[folder]
        source_span=snapshot_interval(w['state'],origin)
        first_span=snapshot_interval(w['response'][0],origin)
        last_span=snapshot_interval(w['response'][-1],origin)
        assert source_span[1]<w['response'][0]['t_apply_us'] or w['state']['kp']==w['action_applied'][0]
        lo,hi=first_span[1],last_span[0]
        aligned=integrate(edges,times,lo,hi)
        source_center=sum(source_span)/2;last_center=sum(last_span)/2
        dt=last_center-source_center;discount=.99**(dt/100000)
        h=w['full_hall_reward'];delta=w['physical_delta_action'][0]
        rate=-aligned['mse_rpm2']/1e6-.3*(h['peak_nominal_current_a']/2)**2-.25*max(0,(aligned['peak_speed_rpm']-1500)/300)**2-.25*h['saturation_fraction']
        corrected=rate*aligned['duration_us']/100000-.0005*delta**2
        values=[integrate(edges,times,a,b)['mse_rpm2'] for a in first_span for b in last_span]
        row=dict(physical_key=w['physical_key'],boot_id=w['boot_id'],split=item['split'],kp=w['action_applied'][0],
            original_reward=w['time_scaled_reward'],sensor_clock_reward=corrected,
            original_mse_rpm2=h['mse_rpm2'],sensor_clock_mse_rpm2=aligned['mse_rpm2'],
            first_snapshot_minus_guard_us=sum(first_span)/2-w['response'][0]['t_us'],
            last_snapshot_minus_guard_us=last_center-w['response'][-1]['t_us'],
            sensor_clock_discount=discount,guard_clock_discount=w['elapsed_discount'],
            source_snapshot_span_us=list(source_span),first_response_snapshot_span_us=list(first_span),
            last_response_snapshot_span_us=list(last_span),conservative_reward_span_us=[lo,hi],
            boundary_corner_mse_range_rpm2=[min(values),max(values)],
            original_replay_window_file=str(path.resolve()),original_replay_window_sha256=item['sha256'])
        rows.append(row);groups[(item['split'],row['kp'])].append(row)
    group_stats=[]
    for (split,kp),items in groups.items():
        group_stats.append(dict(split=split,kp=kp,windows=len(items),
            original_mean_reward=mean(r['original_reward'] for r in items),
            sensor_clock_mean_reward=mean(r['sensor_clock_reward'] for r in items),
            mean_absolute_reward_change=mean(abs(r['sensor_clock_reward']-r['original_reward']) for r in items),
            old_window_rmse_rpm=math.sqrt(mean(r['original_mse_rpm2'] for r in items)),
            sensor_window_rmse_rpm=math.sqrt(mean(r['sensor_clock_mse_rpm2'] for r in items))))
    report=dict(passed=True,unique_windows=len(rows),groups=group_stats,rows=rows,
        first_snapshot_minus_guard_us_range=[min(r['first_snapshot_minus_guard_us'] for r in rows),max(r['first_snapshot_minus_guard_us'] for r in rows)],
        mean_absolute_reward_change=mean(abs(r['sensor_clock_reward']-r['original_reward']) for r in rows),
        max_absolute_reward_change=max(abs(r['sensor_clock_reward']-r['original_reward']) for r in rows),
        raw_packets_modified=False,old_rewards_modified=False,primary_plateau_metric_unchanged=True,
        hardware_accessed=False,training_performed=False,candidate_admission=False,
        deployment_allowed=False,performance_claim_allowed=False,
        source_manifest_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        boundary_uncertainty_is_float32_timestamp_quantization=True)
    assert not Path(output).exists();Path(output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();audit(a.replay,a.output)
