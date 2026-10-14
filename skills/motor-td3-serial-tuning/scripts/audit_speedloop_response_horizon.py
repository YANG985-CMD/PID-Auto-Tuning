"""Describe measured post-switch response horizons, without changing rewards.

Uses full raw Hall held-time integrals. There is no matched counterfactual:
startup, order, drift and prior gain can confound the observed association.
"""
import argparse
import bisect
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin
from speedloop_stream_training import KI

BINS=((0,100000),(100000,200000),(200000,500000),(500000,1000000),
      (1000000,2000000),(2000000,4000000),(4000000,7000000),(7000000,8500000))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))

def integral(edges,begin,end,reference=1000):
    if end<=begin:raise ValueError('Positive scored interval required')
    if not edges:raise ValueError('Missing Hall edges')
    times=[e['t_us'] for e in edges]
    start=bisect.bisect_right(times,begin)-1;stop=bisect.bisect_left(times,end)
    if start<0 or stop>=len(edges):raise ValueError('Incomplete Hall span')
    covered=mse=error=0.;peak=0.;used=0
    for a,b in zip(edges[start:stop],edges[start+1:stop+1]):
        if (b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us']
            or not a['valid'] or a['model_stage']!=4):raise ValueError('Broken Hall evidence')
        width=max(0,min(end,b['t_us'])-max(begin,a['t_us']))
        if width:
            covered+=width;mse+=(a['rpm']-reference)**2*width;error+=(reference-a['rpm'])*width
            peak=max(peak,abs(a['rpm']));used+=1
    if covered!=end-begin:raise ValueError('Uncovered scored interval')
    return dict(begin_us=begin,end_us=end,duration_us=covered,mse_rpm2=mse/covered,
        raw_Hall_RMSE_rpm=math.sqrt(mse/covered),mean_error_rpm=error/covered,
        peak_raw_Hall_speed_rpm=peak,contributing_intervals=used)

def audit(replay,output):
    replay=Path(replay);output=Path(output)
    if output.exists():raise ValueError('One-use audit output already exists')
    data=read(replay/'summary.json');assert data['passed']
    rows=[];sources=[];rewardSpans=[];unique=set()
    for item in data['input_manifest']:
        if sha(item['file'])!=item['sha256']:raise ValueError('Replay window changed')
        w=read(item['file']);rewardSpans.append(w['measured_reward_span_us'])
    for entry in data['whole_boot_split']:
        folder=Path(entry['raw_folder']);q=read(folder/'trial/summary.json')
        if (not q['passed'] or q['final_irq_fault'] or q['final_tx_fault'] or q['actor_applied']
            or not q['protocol_stop_acknowledged'] or not q['core_halted_after_physical_shutdown']
            or not q['can_released_after_shutdown']):raise ValueError('Incomplete stop/fault evidence')
        fullpath=folder/'full-hall-audit/full-hall-edges.json';full=read(fullpath)
        if full['boot_id']!=entry['boot_id'] or full['boot_id'] in unique:raise ValueError('Duplicate or mixed boot')
        unique.add(full['boot_id']);assert full['full_session_history']
        edges=[e for e in full['records'] if e['model_stage']==4]
        packetpath=folder/'trial/telemetry.jsonl'
        packets=[json.loads(line) for line in packetpath.read_text(encoding='utf-8').splitlines()]
        commandpath=folder/'trial/commands.jsonl'
        commands={c['command_seq']:c for line in commandpath.read_text(encoding='utf-8').splitlines()
            if (c:=json.loads(line))['type']=='gains'}
        origin=capture_origin(packets);active=[p for p in packets if p['enabled'] and p['applied_seq']]
        if any(p['fault'] or p['ki']!=KI or p['speed_ref']!=1000 for p in active):raise ValueError('Invalid active trace')
        changes=[];previous=None
        for p in active:
            if previous is not None and p['kp']!=previous['kp']:
                c=commands[p['applied_seq']]
                if c['kp']!=p['kp'] or c['ki']!=p['ki'] or not c['source_t_us']<=p['t_apply_us']<=c['expires_us']:
                    raise ValueError('Missing actual switch ACK')
                changes.append(dict(source_kp=previous['kp'],target_kp=p['kp'],apply_us=p['t_apply_us'],seq=p['applied_seq']))
            previous=p
        for index,c in enumerate(changes):
            end=changes[index+1]['apply_us'] if index+1<len(changes) else active[-1]['t_us']
            if c['apply_us']-origin<3800000:continue
            bins=[]
            for low,high in BINS:
                if c['apply_us']+high>end:continue
                value=integral(edges,c['apply_us']+low,c['apply_us']+high)
                pts=[p for p in active if value['begin_us']<=p['t_us']<value['end_us']]
                value.update(post_actual_application_ms=[low/1000,high/1000],
                    nominal_peak_current_a=max((p['current'] for p in pts),default=None),telemetry_samples=len(pts))
                bins.append(value)
            row=dict(boot_id=entry['boot_id'],split=entry['split'],raw_folder=str(folder),
                source_kp=c['source_kp'],target_kp=c['target_kp'],actual_gain_command_seq=c['seq'],
                actual_application_us=c['apply_us'],elapsed_since_BEGIN_ms=(c['apply_us']-origin)/1000,
                uninterrupted_actual_gain_hold_ms=(end-c['apply_us'])/1000,
                pre_switch_last_1s=integral(edges,c['apply_us']-1000000,c['apply_us']),post_switch_bins=bins)
            rows.append(row)
        sources.append(dict(boot_id=entry['boot_id'],split=entry['split'],raw_folder=str(folder),
            Hall_sha256=sha(fullpath),telemetry_sha256=sha(packetpath),commands_sha256=sha(commandpath)))
    groups=defaultdict(list)
    for r in rows:
        for b in r['post_switch_bins']:
            key=(r['source_kp'],r['target_kp'],*b['post_actual_application_ms']);groups[key].append((r,b))
    aggregate=[]
    for key,values in sorted(groups.items()):
        total=sum(b['duration_us'] for _,b in values)
        aggregate.append(dict(source_kp=key[0],target_kp=key[1],post_application_ms=list(key[2:]),
            actual_switches=len(values),independent_boots=len({r['boot_id'] for r,_ in values}),
            raw_Hall_RMSE_rpm=math.sqrt(sum(b['mse_rpm2']*b['duration_us'] for _,b in values)/total),
            mean_error_rpm=sum(b['mean_error_rpm']*b['duration_us'] for _,b in values)/total))
    sortedSpans=sorted(rewardSpans);count=len(sortedSpans)
    report=dict(passed=True,source_replay_sha256=sha(replay/'summary.json'),rows=rows,groups=aggregate,sources=sources,
        actual_switches_audited=len(rows),independent_physical_boots=len(unique),
        reward_window_duration_ms_min_median_max=[sortedSpans[0]/1000,sortedSpans[count//2]/1000,sortedSpans[-1]/1000],
        diagnostics_declared_after_data=True,reward_or_primary_metric_changed=False,
        correlation_not_gain_causality=True,measured_timing_does_not_prove_settling_time=True,
        no_matched_counterfactual=True,hardware_accessed=False,training_performed=False,
        actor_applied=False,candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','groups','sources')}));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();audit(a.replay,a.output)
