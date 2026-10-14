"""Causal telemetry history and an explicitly bounded trial learning contract.

Original physical observations/rewards/termination flags are never rewritten.
The bounded learning task ends only after a real successful STOP and shutdown.
No interpolation, policy effects, synthesized motor responses or hardware calls.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from speedloop_response_windows import lines,state,temporal_mean,write


def history(telemetry,index):
    if index<2:raise ValueError('Missing causal history')
    past=telemetry[index-2:index+1]
    if not all(r['enabled'] and r['fault']==0 for r in past):raise ValueError('History crosses stop/fault')
    if not all(b['seq']==a['seq']+1 and 15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(past,past[1:])):
        raise ValueError('History is not adjacent 20ms telemetry')
    r=past[-1]
    observation=[v/s for v,s in zip(state(r),[1000,1000,1000,1000,3,2,24,.003389,.00144,3000])]
    observation[3]=(past[-2]['speed_ref']-past[-2]['speed'])/1000
    observation[8]=(past[-3]['speed_ref']-past[-3]['speed'])/1000
    return [max(-5,min(5,v)) for v in observation],dict(
        source_seq=r['seq'],past_sequences=[p['seq'] for p in past[:-1]],
        past_t_us=[p['t_us'] for p in past[:-1]],
        past_errors_rpm=[p['speed_ref']-p['speed'] for p in past[:-1]])


def run(source,output):
    source,out=Path(source).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    summary=json.loads((source/'window-summary.json').read_text(encoding='utf-8'))
    if hashlib.sha256((source/'response-windows.jsonl').read_bytes()).hexdigest()!=summary['dataset_sha256']:
        raise ValueError('Source hash mismatch')
    for f,h in summary['input_files_sha256'].items():
        if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h:raise ValueError('Physical input changed')
    rows=lines(source/'response-windows.jsonl');byboot=defaultdict(list);data={};rounds={}
    for path,digest in summary['raw_telemetry_sha256'].items():
        p=Path(path);raw=lines(p/'telemetry.jsonl');boot=raw[0]['boot_id']
        if boot in data:raise ValueError('Duplicate boot')
        s=json.loads((p/'summary.json').read_text(encoding='utf-8'))
        if not s['passed'] or s['final_irq_fault'] or s['final_tx_fault']:
            raise ValueError('Faulted trial')
        if not all(s[k] for k in ('protocol_stop_acknowledged','core_halted_after_physical_shutdown','can_released_after_shutdown')):
            raise ValueError('Incomplete bounded termination evidence')
        if hashlib.sha256((p/'telemetry.jsonl').read_bytes()).hexdigest()!=digest:raise ValueError('Raw hash mismatch')
        data[boot]=raw;rounds[boot]=s
    for index,r in enumerate(rows):byboot[r['boot_id']].append(index)
    for boot,indices in byboot.items():
        raw=data[boot];positions={p['t_us']:i for i,p in enumerate(raw)}
        for index in indices:
            r=rows[index]
            ho,proof=history(raw,positions[r['t_state_us']])
            hn,nextproof=history(raw,positions[r['t_next_us']])
            r.update(history_observation=ho,history_next_observation=hn,
                history_source_proof=proof,history_next_proof=nextproof,
                learning_is_done=False,learning_reward=r['reward'],
                learning_next_observation=r['next_observation'],
                learning_history_next_observation=hn)
        for a,b in zip(indices,indices[1:]):
            if rows[a]['t_next_us']!=rows[b]['t_state_us'] or rows[a]['next_state']!=rows[b]['state']:
                raise ValueError('Cannot label a bounded return across missing state chain')
        last=rows[indices[-1]]
        active=[p for p in raw if p['enabled']]
        final=active[-1]
        stopped=next(p for p in raw if p['seq']>final['seq'] and not p['enabled'])
        tail=[p for p in raw if last['t_effective_us']<p['t_us']<=final['t_us']]
        if not all(p['enabled'] and p['fault']==0 and [p['kp'],p['ki']]==last['action_applied'] for p in tail):
            raise ValueError('Last response changes action before STOP')
        times=[p['t_us'] for p in tail]
        mse=temporal_mean([(p['speed_ref']-p['speed'])**2 for p in tail],times)
        current=max(abs(p['current']) for p in tail);speed=max(abs(p['speed']) for p in tail)
        saturation=temporal_mean([float(abs(p['current'])>=1.98) for p in tail],times)
        reward=-mse/1e6-.12*(current/2)**2-.08*max(0,(speed-1500)/300)**2-.10*saturation-.005*sum(v*v for v in last['action_normalized'])
        final_obs=[max(-5,min(5,v/s)) for v,s in zip(state(final),[1000,1000,1000,1000,3,2,24,.003389,.00144,3000])]
        hist_final,finalproof=history(raw,positions[final['t_us']])
        last.update(learning_is_done=True,learning_reward=reward,
            learning_next_observation=final_obs,learning_history_next_observation=hist_final,
            bounded_response_telemetry_seqs=[p['seq'] for p in tail],bounded_next_t_us=final['t_us'],
            bounded_history_next_proof=finalproof,
            bounded_terminal_evidence=dict(stop_seq=stopped['seq'],stop_t_us=stopped['t_us'],
                last_active_seq=final['seq'],last_active_t_us=final['t_us'],
                physical_timing_stop_us=rounds[boot]['trial_timing']['last_us'],fault=stopped['fault'],
                stop_acknowledged=True,outputs_off=True,core_halted=True,can_released=True),
            learning_terminal_reason='completed planned bounded trial; no fault relabeling')
        total=0.0
        for index in reversed(indices):
            total=rows[index]['learning_reward']+.99*total
            rows[index]['logged_bounded_return']=total
    out.mkdir(parents=True,exist_ok=False)
    blob=b''.join((json.dumps(r,allow_nan=False)+'\n').encode() for r in rows)
    (out/'response-windows.jsonl').write_bytes(blob)
    updated=dict(summary)
    updated.update(data_revision='causal-history-bounded-task-v1',parent_dataset_sha256=summary['dataset_sha256'],
        dataset_sha256=hashlib.sha256(blob).hexdigest(),history_depth_packets=2,
        history_source='previous two adjacent actual telemetry packets, nominal 20/40ms',
        physical_fields_and_flags_preserved=True,bounded_done_rows=len(byboot),
        bounded_task='Same limited motor trial including known STOP; alternative to continuing-control value task',
        bounded_horizon_ms=8000,default_continuing_training_unchanged=True,
        logged_return_policy='actual recorded behavior continuation; not the return of a new Actor',
        performance_metric_unchanged=True,actor_deployed=False,deployment_allowed=False)
    updated['input_file_manifest']=[dict(path=p,sha256=h) for p,h in summary['input_files_sha256'].items()]
    write(out/'window-summary.json',updated)
    print(json.dumps(dict(rows=len(rows),train=updated['training_windows'],validation=updated['validation_windows'],
                         bounded_done=len(byboot),dataset_sha256=updated['dataset_sha256'])))
    return updated


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.output)
