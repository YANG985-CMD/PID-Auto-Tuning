"""Append independently audited late RunStage data, keeping Ki exactly fixed.

Preserve historical boot holdouts. New baseline is holdout, new Kp-probe boot
is training. No duplicate raw data, fabricated transitions or hardware access.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
from speedloop_response_windows import lines,write,build_trial
from stitch_speedloop_replay import extend


def run(repository,source,batch,output):
    repository,source,batch,out=map(lambda p:Path(p).resolve(),(repository,source,batch,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    old=json.loads((source/'window-summary.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((source/'response-windows.jsonl').read_bytes()).hexdigest()==old['dataset_sha256']
    assert old['window_profile']=='strict' and not old['exploratory_only']
    collection=json.loads((batch/'collection-summary.json').read_text(encoding='utf-8'))
    assert collection['passed'] and len(collection['rounds'])==2
    hashes=dict(old['raw_telemetry_sha256'])
    for path,digest in hashes.items():
        raw=repository/path/'telemetry.jsonl'
        assert hashlib.sha256(raw.read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest
    historical=lines(source/'response-windows.jsonl')
    fixed_ki=struct.unpack('<f',struct.pack('<f',.00144))[0]
    rows=[r for r in historical if r['action_applied'][1]==fixed_ki and r['state'][8]==fixed_ki and
          r['next_state'][8]==fixed_ki and abs(r['action_normalized'][1])<1e-7]
    oldboots={r['boot_id'] for r in historical}
    start_index=max(r['run_index'] for r in historical)+1
    rejection=[];new_counts=[];holdout=list(old['validation_run_indices'])+[start_index]
    for index,path in enumerate(sorted(batch.glob('round-*')),start_index):
        raw=lines(path/'trial/telemetry.jsonl')
        audit=json.loads((path/'audit/analysis.json').read_text(encoding='utf-8'))
        trial=json.loads((path/'trial/summary.json').read_text(encoding='utf-8'))
        assert audit['passed'] and trial['passed'] and trial['firmware_id']=='g431-speedloop-pi-response-8s-v7'
        assert raw[0]['boot_id'] not in oldboots;oldboots.add(raw[0]['boot_id'])
        assert (index==start_index)==(trial['gain_mode']=='baseline')
        digest=hashlib.sha256((path/'trial/telemetry.jsonl').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        assert digest not in hashes.values();hashes[str(path/'trial')]=digest
        cs=[r for r in lines(path/'audit/experience-candidates.jsonl') if r['stage_confirmed_from_raw_edges']]
        for r in cs:r.update(run_index=index,boot_id=raw[0]['boot_id'],validation_split=index in holdout)
        kept,refused=build_trial(cs,raw)
        for k in range(len(kept)-1):
            kept[k],reason=extend(kept[k],kept[k+1],raw)
            assert reason is None,'Never stitch a changed or unproven gain'
        response_seqs=[seq for r in kept for seq in r['response_telemetry_seqs']]
        assert len(response_seqs)==len(set(response_seqs))
        assert all(r['action_applied'][1]==fixed_ki and r['action_normalized'][1]==0 for r in kept)
        rows.extend(kept);rejection.extend(refused)
        new_counts.append(dict(run_index=index,boot_id=raw[0]['boot_id'],windows=len(kept),
            validation_split=index in holdout,nonzero_kp_changes=sum(abs(r['action_normalized'][0])>1e-7 for r in kept)))
    train=[r for r in rows if not r['validation_split']];validation=[r for r in rows if r['validation_split']]
    assert {r['boot_id'] for r in train}.isdisjoint({r['boot_id'] for r in validation})
    out.mkdir(parents=True,exist_ok=False)
    blob=b''.join((json.dumps(r,allow_nan=False)+'\n').encode() for r in rows)
    (out/'response-windows.jsonl').write_bytes(blob)
    report=dict(old)
    report.update(source_sessions=old['source_sessions']+2,response_windows=len(rows),
        training_windows=len(train),validation_windows=len(validation),
        data_revision='late-RunStage-fixed-Ki-append-v1',parent_dataset_sha256=old['dataset_sha256'],
        dataset_sha256=hashlib.sha256(blob).hexdigest(),action_mask=[1,0],fixed_ki=fixed_ki,
        historical_fixed_ki_windows=len(rows)-sum(r['windows'] for r in new_counts),
        excluded_historical_variable_ki_windows=len(historical)-(len(rows)-sum(r['windows'] for r in new_counts)),
        new_sessions=new_counts,validation_run_indices=holdout,raw_telemetry_sha256=hashes,
        response_sample_count_histogram=dict(Counter(r['response_sample_count'] for r in rows)),
        ki_nonzero_delta_windows=0,training_ready=len(train)>=128 and bool(validation),
        replay_count_ready=len(train)>=128 and bool(validation),
        all_boot_ids=sorted(oldboots),ordinary_deployment_allowed=False,performance_claim_allowed=False,
        candidate_admission_passed=False,td3_training_performed=False)
    write(out/'window-summary.json',report);write(out/'rejected-new-groups.json',rejection)
    print(json.dumps(dict(training=len(train),validation=len(validation),new_sessions=new_counts,
        dataset_sha256=report['dataset_sha256'],training_ready=report['training_ready'])))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('repository','source','batch','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.repository,a.source,a.batch,a.output)
