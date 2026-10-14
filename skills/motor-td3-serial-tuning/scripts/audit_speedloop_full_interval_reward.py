"""Observe all state-to-next-state costs, including measured command latency."""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from build_speedloop_fullhall_replay import read,sha
from speedloop_response_windows import temporal_mean


def integrate(edges,times,lo,hi,reference):
    start=bisect.bisect_right(times,lo)-1;end=bisect.bisect_left(times,hi)
    if start<0 or end>=len(edges) or hi<=lo:raise ValueError('Incomplete full decision Hall interval')
    trace=edges[start:end+1];duration=mse=0.;peak=0.
    for a,b in zip(trace,trace[1:]):
        if not a['valid'] or a['model_stage']!=4 or b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us']:
            raise ValueError('Full decision Hall gap')
        width=max(0,min(hi,b['t_us'])-max(lo,a['t_us']));duration+=width;mse+=width*(a['rpm']-reference)**2
        if width:peak=max(peak,abs(a['rpm']))
    if duration!=hi-lo:raise ValueError('Uncovered full decision reward')
    return dict(begin_us=lo,end_us=hi,duration_us=duration,mse_rpm2=mse/duration,peak_speed_rpm=peak,records=trace)


def validate_packet(packet,proof,commands,window):
    p=packet
    if (not all(math.isfinite(p[k]) for k in ('speed','current','vbus','integral_output'))
        or not abs(p['speed'])<1800 or not 0<=p['current']<2 or not 18<=p['vbus']<=30):
        raise ValueError('Full decision physical measurement boundary')
    if (p['boot_id']!=window['boot_id'] or not p['enabled'] or p['fault'] or p['ki']!=window['action_applied'][1]
        or p['kp'] not in (window['state']['kp'],window['action_applied'][0])
        or p['speed_ref']!=window['full_hall_reward']['reference_rpm']):
        raise ValueError('Fault, reference step or unrelated actual gain in full decision interval')
    if (proof is None or proof['started']!=1 or proof['run_seen']!=1 or proof['fault'] or proof['irq_fault']
        or not proof['started_us']<=proof['run_started_us']<=p['t_us']<=proof['last_us']
        or abs((p['t_us']-proof['started_us'])/1000-p['elapsed_ms'])>2):
        raise ValueError('Full decision RunStage proof missing')
    c=commands.get(p['applied_seq'])
    if (c is None or (c['kp'],c['ki'])!=(p['kp'],p['ki'])
        or not c['source_t_us']<=p['t_apply_us']<=c['expires_us'] or p['t_apply_us']>p['t_us']+2):
        raise ValueError('Full decision actual gain application not confirmed')


def audit(replay,output):
    replay,output=Path(replay),Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest=read(replay/'summary.json');assert manifest['passed'] and manifest['split_frozen_before_gradients']
    cache={};rows=[];seen=set()
    for item in manifest['input_manifest']:
        path=Path(item['file']);assert sha(path)==item['sha256'];w=read(path)
        if w['physical_key'] in seen:raise ValueError('Duplicate physical reward interval')
        seen.add(w['physical_key']);raw=Path(item['raw_window_file']);folder=raw.parent.parent
        assert sha(raw)==item['raw_window_sha256']
        if folder not in cache:
            events_path=folder/'stream/events.jsonl';events=[json.loads(line) for line in events_path.read_text().splitlines()]
            event_audit=read(folder/'full-hall-audit/summary.json');assert event_audit['passed']
            assert sha(events_path)==event_audit['hashes']['events.jsonl']
            packets={e['packet']['seq']:e for e in events if e['kind']=='telemetry'}
            commands={e['command']['command_seq']:e['command'] for e in events
                if e['kind']=='command' and e['command']['type']=='gains'}
            hall=folder/'full-hall-audit/full-hall-edges.json';assert sha(hall)==w['full_hall_reward']['full_hall_sha256']
            edges=[e for e in read(hall)['records'] if e['model_stage']==4]
            cache[folder]=(packets,commands,edges,[e['t_us'] for e in edges],sha(events_path),sha(hall))
        events,commands,edges,times,event_sha,hall_sha=cache[folder]
        selected=[];proofs=[]
        for seq in range(w['state']['seq'],w['response'][-1]['seq']+1):
            if seq not in events:raise ValueError('Missing packet in unscored prefix')
            event=events[seq];packet=event['packet'];proof=event['stage_proof']
            validate_packet(packet,proof,commands,w);selected.append(packet);proofs.append(proof)
        assert selected[0]==w['state'] and selected[-len(w['response']):]==w['response']
        assert all(15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(selected,selected[1:]))
        lo,hi=selected[0]['t_us'],selected[-1]['t_us'];assert hi-lo==w['duration_us']
        h=integrate(edges,times,lo,hi,w['full_hall_reward']['reference_rpm'])
        current=max(p['current'] for p in selected)
        saturation=temporal_mean([float(p['current']>=1.98) for p in selected],[p['t_us'] for p in selected])
        delta=w['physical_delta_action'][0]
        reward=(-h['mse_rpm2']/1e6-.3*(current/2)**2-.25*max(0,(h['peak_speed_rpm']-1500)/300)**2-.25*saturation)*h['duration_us']/100000-.0005*delta**2
        first_scored=w['response'][0]['t_us'];omitted=first_scored-lo
        first_applied=lo
        if w['state']['kp']!=w['action_applied'][0]:
            actual=[p for p in selected if p['kp']==w['action_applied'][0]]
            assert actual;first_applied=actual[0]['t_apply_us']
            if actual[0]['applied_seq']<w['first_command_seq']:raise ValueError('An earlier unmodeled target command was already pending')
        r=dict(physical_key=w['physical_key'],boot_id=w['boot_id'],split=item['split'],
            source_window_file=str(path.resolve()),source_window_sha256=item['sha256'],
            raw_window_file=str(raw.resolve()),raw_window_sha256=item['raw_window_sha256'],
            source_events_sha256=event_sha,source_full_hall_sha256=hall_sha,
            packets=selected,stage_proofs=proofs,full_hall_interval=h,
            full_interval_peak_nominal_current_a=current,full_interval_saturation_fraction=saturation,
            original_post_ack_reward=w['time_scaled_reward'],full_decision_reward=reward,
            original_scored_span_us=w['measured_reward_span_us'],decision_duration_us=w['duration_us'],
            omitted_prefix_us=omitted,omitted_prefix_fraction=omitted/w['duration_us'],
            measured_first_new_gain_apply_us=first_applied,
            measured_before_new_gain_us=max(0,first_applied-lo),
            actual_source_kp=w['state']['kp'],actual_target_kp=w['action_applied'][0],
            physical_delta_action=w['physical_delta_action'],actual_action_and_next_state_unchanged=True,
            old_rewards_preserved=True,prefix_not_labeled_as_all_new_gain=True,
            candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
        rows.append(r)
    table=output/'full-interval-windows.jsonl';table.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    summary=dict(passed=True,unique_windows=len(rows),counts=manifest['counts'],
        source_manifest_sha256=sha(replay/'summary.json'),full_interval_rows_sha256=sha(table),
        mean_omitted_prefix_fraction=mean(r['omitted_prefix_fraction'] for r in rows),
        omitted_prefix_us_range=[min(r['omitted_prefix_us'] for r in rows),max(r['omitted_prefix_us'] for r in rows)],
        mean_original_post_ack_reward=mean(r['original_post_ack_reward'] for r in rows),
        mean_full_decision_reward=mean(r['full_decision_reward'] for r in rows),
        mean_before_new_gain_us_on_switches=mean(r['measured_before_new_gain_us'] for r in rows if r['actual_source_kp']!=r['actual_target_kp']),
        all_prefix_packets_and_actual_gains_verified=True,reward_variant='full-decision-observed-latency-v1',
        alternate_training_reward_not_new_motor_samples=True,new_physical_windows=0,
        raw_logs_modified=False,old_rewards_modified=False,primary_performance_metric_changed=False,
        hardware_accessed=False,training_performed=False,candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();audit(a.replay,a.output)
