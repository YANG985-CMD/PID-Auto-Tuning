"""Build a phase-specific replay with complete-pair held-out boot sessions.

Keeps measured actions, actual acknowledgements and strict response grouping.
Startup records are excluded, not relabelled as steady operation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from speedloop_response_windows import lines,write,build_trial
from stitch_speedloop_replay import extend


def run(repository,source,session,output):
    repository,source,session,out=map(lambda p:Path(p).resolve(),(repository,source,session,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    old=json.loads((source/'window-summary.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((source/'response-windows.jsonl').read_bytes()).hexdigest()==old['dataset_sha256']
    contract=json.loads((session.parent/'analysis-contract.json').read_text(encoding='utf-8'))
    collected=json.loads((session/'session-summary.json').read_text(encoding='utf-8'))
    assert collected['passed'] and contract['new_validation_pairs']==[1] and contract['new_training_pairs']==[2,3]
    historical=lines(source/'response-windows.jsonl')
    rows=[r for r in historical if r['firmware_id']=='g431-speedloop-pi-response-8s-v7' and r['state'][9]>=3900]
    retained_historical=len(rows)
    hashes=dict(old['raw_telemetry_sha256'])
    for path,digest in hashes.items():
        assert hashlib.sha256((repository/path/'telemetry.jsonl').read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest
    boots=set(old['all_boot_ids']);holdout=list(old['validation_run_indices'])
    index=max(r['run_index'] for r in historical);new_sessions=[];refused=[]
    for pair in range(1,4):
        for path in sorted((session/f'pair-{pair:02d}').glob('round-*')):
            index+=1
            raw=lines(path/'trial/telemetry.jsonl')
            trial=json.loads((path/'trial/summary.json').read_text(encoding='utf-8'))
            audit=json.loads((path/'audit/analysis.json').read_text(encoding='utf-8'))
            assert trial['passed'] and audit['passed'] and trial['firmware_id']=='g431-speedloop-pi-response-8s-v7'
            boot=raw[0]['boot_id'];assert boot not in boots;boots.add(boot)
            digest=hashlib.sha256((path/'trial/telemetry.jsonl').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            assert digest not in hashes.values();hashes[str(path/'trial')]=digest
            validation=pair in contract['new_validation_pairs']
            if validation:holdout.append(index)
            cs=[r for r in lines(path/'audit/experience-candidates.jsonl') if r['stage_confirmed_from_raw_edges'] and r['state'][9]>=3900]
            for r in cs:r.update(run_index=index,boot_id=boot,validation_split=validation)
            kept,rejected=build_trial(cs,raw)
            for k in range(len(kept)-1):
                kept[k],reason=extend(kept[k],kept[k+1],raw);assert reason is None
            used=[seq for r in kept for seq in r['response_telemetry_seqs']]
            assert len(used)==len(set(used))
            rows.extend(kept);refused.extend(rejected)
            new_sessions.append(dict(run_index=index,pair=pair,mode=trial['gain_mode'],boot_id=boot,
                                     validation_split=validation,windows=len(kept)))
    train=[r for r in rows if not r['validation_split']];validation=[r for r in rows if r['validation_split']]
    assert {r['boot_id'] for r in train}.isdisjoint({r['boot_id'] for r in validation})
    assert all(r['action_normalized'][1]==0 and r['action_applied'][1]==old['fixed_ki'] for r in rows)
    out.mkdir(parents=True,exist_ok=False)
    blob=b''.join((json.dumps(r,allow_nan=False)+'\n').encode() for r in rows)
    (out/'response-windows.jsonl').write_bytes(blob)
    summary=dict(old)
    summary.update(data_revision='steady-phase-complete-pair-holdout-v1',parent_dataset_sha256=old['dataset_sha256'],
        dataset_sha256=hashlib.sha256(blob).hexdigest(),source_sessions=8,response_windows=len(rows),
        training_windows=len(train),validation_windows=len(validation),training_ready=len(train)>=128,
        replay_count_ready=len(train)>=128,validation_run_indices=sorted({r['run_index'] for r in validation}),raw_telemetry_sha256=hashes,
        steady_phase_minimum_elapsed_ms=3900,excluded_startup_windows=len(historical)-retained_historical,
        historical_fixed_ki_windows=retained_historical,excluded_historical_variable_ki_windows=0,
        new_sessions=new_sessions,all_boot_ids=sorted({r['boot_id'] for r in rows}),
        lineage_boot_ids=sorted(boots),raw_hash_scope='Included sessions plus validated parent lineage',action_mask=[1,0],
        response_sample_count_histogram=dict(Counter(r['response_sample_count'] for r in rows)),
        observed_span_ms_range=[min(r['observed_response_span_ms'] for r in rows),max(r['observed_response_span_ms'] for r in rows)],
        transition_duration_ms_range=[min(r['transition_duration_ms'] for r in rows),max(r['transition_duration_ms'] for r in rows)],
        action_support='Recorded baseline or baseline +4%; negative deltas are returns, not below-baseline exploration',
        deployment_allowed=False,performance_claim_allowed=False,td3_training_performed=False)
    write(out/'window-summary.json',summary);write(out/'rejected-new-groups.json',refused)
    print(json.dumps(dict(training=len(train),validation=len(validation),new_sessions=new_sessions,dataset_sha256=summary['dataset_sha256'])))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('repository','source','session','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.repository,a.source,a.session,a.output)
