"""Offline longer-response view from exact real-time journals.

Each view replaces the short windows; views cannot be appended together as
independent new physical data. No device access, synthetic response or gains.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
from speedloop_stream_training import CausalStream,UPPER8_DENSE_GAINS,BIDIRECTIONAL_V27_GAINS

read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def reconstruct(replay,output,minimum_span_us):
    if minimum_span_us not in (200000,300000):raise ValueError('Predeclared alternate spans only')
    replay=Path(replay);output=Path(output)
    if output.exists():raise ValueError('One-use view output required')
    summary=read(replay/'summary.json');assert summary['passed']
    if summary['stream_gain_profile']=='upper8-dense-fullhall':gains=UPPER8_DENSE_GAINS
    elif summary['stream_gain_profile']=='bidirectional16-upper8-fullhall':gains=BIDIRECTIONAL_V27_GAINS
    else:raise ValueError('Unreviewed alternate action profile')
    output.mkdir(parents=True);boots=[];keys=set();counts={'train':0,'validation':0};actions=Counter();switches=Counter();mapping_metadata_changes=0
    for index,entry in enumerate(summary['whole_boot_split']):
        source=Path(entry['raw_folder']);trial=read(source/'trial/summary.json');ending=read(source/'stream/session-ended.json')
        full=read(source/'full-hall-audit/summary.json')
        assert trial['passed'] and not trial['final_irq_fault'] and not trial['final_tx_fault'] and not trial['actor_applied']
        assert all(ending[k] for k in ('physical_trial_passed','stop_acknowledged','core_halted','can_released'))
        assert full['passed'] and full['boot_id']==entry['boot_id']
        eventpath=source/'stream/events.jsonl';eventDigest=sha(eventpath);assert eventDigest==full['hashes']['events.jsonl']
        default=CausalStream(gains);alternate=CausalStream(gains,minimum_span_us)
        folder=output/f"boot-{index:02d}";stream=folder/'stream';stream.mkdir(parents=True)
        originalFiles=sorted((source/'stream').glob('window-*.json'));matched=0;boot_mapping_changes=0
        for line in eventpath.read_text(encoding='utf-8').splitlines():
            event=json.loads(line)
            if event['kind']=='command':
                for view in (default,alternate):view.command(event['command'],event['source'])
            elif event['kind']=='telemetry':
                a=default.telemetry(event['packet'],event['stage_proof'])
                b=alternate.telemetry(event['packet'],event['stage_proof'])
                if a:
                    original=read(originalFiles[matched])
                    if a!=original and gains==BIDIRECTIONAL_V27_GAINS:
                        differences={k for k in a.keys()|original.keys() if a.get(k)!=original.get(k)}
                        assert differences=={'action_mapping_redefinition_required'} and a['action_mapping_redefinition_required'] is True and original['action_mapping_redefinition_required'] is False,'Physical journal replay differs'
                        mapping_metadata_changes+=1
                        boot_mapping_changes+=1
                    else:assert a==original,'Default journal replay differs from original stored physical window'
                    matched+=1
                if b:
                    assert b['boot_id']==entry['boot_id'] and b['response'][-1]['t_us']-b['response'][0]['t_us']>=minimum_span_us
                    key=f"{b['boot_id']}:{b['first_command_seq']}:{b['response'][-1]['seq']}"
                    assert key not in keys;keys.add(key)
                    counts[entry['split']]+=1;target=b['action_applied'][0]
                    actions[(entry['split'],target)]+=1
                    switches[(entry['split'],target,b['state']['kp']!=target)]+=1
                    b.update(historical_reconstruction=True,minimum_post_ACK_response_span_us=minimum_span_us,
                        new_physical_trial=False,original_realtime_journal_sha256=eventDigest)
                    (stream/f'window-{alternate.windows:05d}.json').write_text(json.dumps(b,allow_nan=False)+'\n',encoding='utf-8')
            else:raise ValueError('Unknown journal event')
        assert matched==len(originalFiles)
        for name in ('trial','full-hall-audit'):shutil.copytree(source/name,folder/name)
        shutil.copy2(eventpath,stream/'events.jsonl');shutil.copy2(source/'stream/session-ended.json',stream/'session-ended.json')
        boots.append(dict(boot_id=entry['boot_id'],split=entry['split'],raw_folder=str(folder.resolve()),
            original_raw_folder=str(source),journal_sha256=eventDigest,original_default_windows_exact=matched-boot_mapping_changes,
            original_default_physical_fields_exact=matched,mapping_annotation_changes=boot_mapping_changes,
            alternate_windows=alternate.windows,rejected_partial_groups=alternate.rejected))
    assert len(keys)==sum(counts.values())
    report=dict(passed=True,source_replay_sha256=sha(replay/'summary.json'),minimum_span_us=minimum_span_us,
        counts=counts,unique_reconstructed_decisions=len(keys),whole_boot_split=boots,
        action_counts=[dict(split=s,target_kp=k,count=n) for (s,k),n in sorted(actions.items())],
        switch_counts=[dict(split=s,target_kp=k,switched=c,count=n) for (s,k,c),n in sorted(switches.items())],
        original_default_windows_reproduced_exactly=sum(b['original_default_windows_exact'] for b in boots),
        original_default_physical_fields_reproduced_exactly=sum(b['original_default_physical_fields_exact'] for b in boots),
        historical_action_mapping_annotation_changes=mapping_metadata_changes,
        exact_default_reproduction_excludes_only_declared_mapping_annotation=mapping_metadata_changes>0,
        same_original_physical_boots=len(boots),new_physical_trials=0,
        alternative_horizon_is_not_additional_independent_physical_data=True,
        append_original_and_alternate_replay_for_training_forbidden=True,
        synthetic_motor_responses_used=False,original_telemetry_actions_and_rewards_unchanged=True,
        raw_Hall_primary_performance_score_unchanged=True,hardware_accessed=False,
        training_performed=False,actor_applied=False,candidate_admission=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (output/'reconstruction-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('whole_boot_split','switch_counts')}));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    p.add_argument('--minimum-span-us',required=True,type=int,choices=(200000,300000));a=p.parse_args()
    reconstruct(a.replay,a.output,a.minimum_span_us)
