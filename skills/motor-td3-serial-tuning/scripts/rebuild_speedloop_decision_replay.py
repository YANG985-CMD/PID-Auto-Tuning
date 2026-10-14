"""Rebuild one causal transition per actual prescribed400ms decision.

Only measured packets and ACKs are used. No interpolation, reward rewrite,
hardware access or old-window duplicate counting. Keeps whole-boot holdout.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from speedloop_fixedref_probe import KP_LEVELS,IDENTITY,IMAGE_SHA
from speedloop_stream_training import CausalStream,KI
from speedloop_response_windows import temporal_mean


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def lines(p):return [json.loads(l) for l in Path(p).read_text(encoding='utf-8').splitlines()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rebuild(folder,split):
    folder=Path(folder).resolve();s=read(folder/'trial/summary.json');ending=read(folder/'stream/session-ended.json')
    if (not s['passed'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
        or s['actor_applied'] or s['final_irq_fault'] or s['final_tx_fault']
        or s['predeclared_split']!=split or not all(ending[k] for k in
            ('physical_trial_passed','stop_acknowledged','core_halted','can_released'))):
        raise ValueError('Physical session or predeclared split invalid')
    events=lines(folder/'stream/events.jsonl');telemetry=[e for e in events if e['kind']=='telemetry']
    raw=[e['packet'] for e in telemetry];commands=[e['command'] for e in events if e['kind']=='command']
    if raw!=lines(folder/'trial/telemetry.jsonl') or commands!=lines(folder/'trial/commands.jsonl'):
        raise ValueError('Retained events differ from raw trace')
    byseq={e['packet']['seq']:e for e in telemetry};bytime={p['t_us']:p for p in raw}
    gains={c['command_seq']:c for c in commands if c['type']=='gains'};first={};tail=None
    for c in gains.values():
        ms=bytime[c['source_t_us']]['elapsed_ms']
        if 4000<=ms<22000:first.setdefault(int((ms-4000)//400),c)
        elif ms>=22000 and tail is None:tail=c
    if set(first)!=set(range(45)) or tail is None:raise ValueError('Missing declared decision boundary')
    decisions=[first[i] for i in range(45)]+[tail];result=[];pairs=Counter()
    for index,(command,next_command) in enumerate(zip(decisions,decisions[1:])):
        state=bytime[command['source_t_us']];next_state=bytime[next_command['source_t_us']]
        expected=KP_LEVELS[s['probe_pattern'][index]]
        if (command['kp'],command['ki'])!=(expected,KI):raise ValueError('Unexpected physical action')
        history=[byseq[i]['packet'] for i in range(state['seq']-2,state['seq']+1)]
        ack=next(p for p in raw if p['applied_seq']==command['command_seq'])
        applied=ack['t_apply_us']
        if not state['t_us']<applied<next_state['t_us'] or applied>command['expires_us']:
            raise ValueError('Decision state/application boundary invalid')
        response=[p for p in raw if applied<p['t_us']<=next_state['t_us']]
        if (len(response)<12 or response[-1]!=next_state
            or any(p['fault'] or not p['enabled'] or p['speed_ref']!=1000
                or (p['kp'],p['ki'])!=(expected,KI) for p in response)
            or any(b['seq']!=a['seq']+1 for a,b in zip(response,response[1:]))):
            raise ValueError('Crossed action or incomplete measured response')
        proofs=[byseq[p['seq']]['stage_proof'] for p in response]
        if not CausalStream.valid_stage(byseq[state['seq']]['stage_proof'],state) or any(
            not CausalStream.valid_stage(proof,p) for proof,p in zip(proofs,response)):
            raise ValueError('Actual stage proof missing')
        dt=next_state['t_us']-state['t_us']
        if not 300000<=dt<=500000:raise ValueError('Unexplained decision duration')
        times=[p['t_us'] for p in response];span=times[-1]-times[0]
        mse=temporal_mean([(p['speed_ref']-p['speed'])**2 for p in response],times)
        current=max(p['current'] for p in response);speed=max(p['speed'] for p in response)
        saturation=temporal_mean([float(p['current']>=1.98) for p in response],times)
        delta=(expected-state['kp'])/.00027112
        legacy=-mse/1e6-.12*(current/2)**2-.08*max(0,(speed-1500)/300)**2-.1*saturation-.005*delta**2
        rate=-mse/1e6-.3*(current/2)**2-.25*max(0,(speed-1500)/300)**2-.25*saturation
        ids=sorted({command['command_seq']}|{p['applied_seq'] for p in response})
        for p in response:
            c=gains[p['applied_seq']]
            if (c['kp'],c['ki'])!=(expected,KI) or not c['source_t_us']<=p['t_apply_us']<=c['expires_us']:
                raise ValueError('Actual refresh ACK invalid')
        pairs[(KP_LEVELS.index(state['kp']),KP_LEVELS.index(expected))]+=1
        result.append(dict(schema_version=1,source='real_motor_live_actual_ack',boot_id=state['boot_id'],
            window_index=index+1,state=state,state_history=history,
            source_stage_proof=byseq[state['seq']]['stage_proof'],response=response,response_stage_proofs=proofs,
            commands=[gains[k] for k in ids],first_command_seq=command['command_seq'],
            t_effective_us=state['t_us'] if state['kp']==expected else applied,
            action_applied=[expected,KI],physical_delta_action=[delta,0],reward=legacy,
            elapsed_discount=.99**(dt/100000),reference_discount=.99,reference_period_us=100000,
            duration_us=dt,measured_reward_span_us=span,
            unscored_pre_application_and_sample_latency_us=dt-span,
            time_scaled_reward=rate*span/100000-.0005*delta**2,
            reward_rate_components=dict(mse_rpm2=mse,peak_nominal_current_a=current,
                peak_speed_rpm=speed,saturation_fraction=saturation),
            terminated=False,truncated=False,session_shutdown_pending=True,
            deployment_allowed=False,performance_claim_allowed=False,actor_applied=False,
            data_revision='one-actual-decision-with-measured-elapsed-time-v1',split=split))
    if any(pairs[(i,j)]!=5 for i in range(3) for j in range(3)):raise ValueError('Actual pair support unbalanced')
    if any(a['response'][-1]!=b['state'] for a,b in zip(result,result[1:])):
        raise ValueError('Consecutive decision states are not linked')
    return result,dict(boot_id=result[0]['boot_id'],split=split,decisions=len(result),
        actual_action_changes=sum(r['state']['kp']!=r['action_applied'][0] for r in result),
        duration_us_range=[min(r['duration_us'] for r in result),max(r['duration_us'] for r in result)],
        discount_range=[min(r['elapsed_discount'] for r in result),max(r['elapsed_discount'] for r in result)],
        measured_span_us_range=[min(r['measured_reward_span_us'] for r in result),max(r['measured_reward_span_us'] for r in result)],
        linked_actual_next_states=True,actual_pair_counts=[[pairs[(i,j)] for j in range(3)] for i in range(3)],
        input_hashes={name:sha(folder/name) for name in ('trial/telemetry.jsonl','trial/commands.jsonl','stream/events.jsonl')})


def run(archive,output):
    archive,output=Path(archive).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents or output.exists():raise ValueError('Fresh task temporary output required')
    rebuilt=[rebuild(archive/'round0','train'),rebuild(archive/'round1','validation')]
    if rebuilt[0][1]['boot_id']==rebuilt[1][1]['boot_id']:raise ValueError('Duplicate boot')
    output.mkdir(parents=True);manifest=[]
    for rows,info in rebuilt:
        folder=output/info['split'];folder.mkdir()
        for row in rows:
            file=folder/f"window-{row['window_index']:05d}.json"
            file.write_text(json.dumps(row,allow_nan=False)+'\n',encoding='utf-8')
            manifest.append(dict(file=str(file),sha256=sha(file),boot_id=row['boot_id'],split=info['split']))
    report=dict(source='audited-real-motor-decision-reconstruction',trials=[r[1] for r in rebuilt],
        physical_boots=2,total_unique_decisions=90,input_manifest=manifest,reference_period_us=100000,
        discount_rule='0.99^(measured state-to-next-state microseconds/100000)',
        time_scaled_reward_rule='measured post-apply cost rate times measured span/100ms; action change penalty charged once',
        unmeasured_latency_cost_estimated=False,old_short_windows_also_appended=False,
        raw_data_modified=False,hardware_accessed=False,training_performed=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['trials']));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.archive,a.output)
