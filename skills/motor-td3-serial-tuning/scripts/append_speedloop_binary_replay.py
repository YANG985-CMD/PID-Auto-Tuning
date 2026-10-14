"""Append audited binary probes to TRAIN only, preserve whole-boot holdout."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from prepare_speedloop_excitation_replay import verified_round
from speedloop_response_windows import lines,write,build_trial
from stitch_speedloop_replay import extend
from speedloop_binary_probe import PATTERNS,planned_gains


def run(source,session,output):
    source,session,out=map(lambda x:Path(x).resolve(),(source,session,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    summary=json.loads((source/'window-summary.json').read_text(encoding='utf-8'))
    if hashlib.sha256((source/'response-windows.jsonl').read_bytes()).hexdigest()!=summary['dataset_sha256']:
        raise ValueError('Parent dataset hash mismatch')
    rows=lines(source/'response-windows.jsonl')
    contract=json.loads((session/'collection-summary.json').read_text(encoding='utf-8'))
    if not contract['passed'] or contract['requested_rounds']!=3 or contract['reserved_batch_motion_seconds']!=24:
        raise ValueError('Incomplete finite binary batch')
    for f,digest in summary['input_files_sha256'].items():
        if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=digest:raise ValueError('Parent input changed')
    original_validation=[r for r in rows if r['validation_split']]
    boots=set(summary['all_boot_ids']);digests=set(summary['raw_telemetry_sha256'].values())
    sessions=list(summary['sessions']);rawhashes=dict(summary['raw_telemetry_sha256']);hashes=dict(summary['input_files_sha256'])
    rejected=[];index=max(s['run_index'] for s in sessions)
    for number in range(1,4):
        path=session/f'round-{number:02d}'
        trial,audit,raw,boot,digest=verified_round(path,boots,digests)
        pattern=trial['probe_schedule_index']
        if trial['gain_mode']!='binary_probe' or trial['probe_schedule']!=list(PATTERNS[pattern]):
            raise ValueError('Unexpected binary actions')
        commands=lines(path/'trial/commands.jsonl')
        origin=trial['trial_timing']['started_us']
        packets={r['t_us']:r for r in raw}
        for c in commands:
            if c['type']=='gains':
                expected=planned_gains(packets[c['source_t_us']]['elapsed_ms'],index=pattern)
                if (c['kp'],c['ki'])!=expected:raise ValueError('Actual command schedule mismatch')
        index+=1
        candidates=[r for r in lines(path/'audit/experience-candidates.jsonl')
                    if r['stage_confirmed_from_raw_edges'] and r['state'][9]>=3900]
        for r in candidates:r.update(run_index=index,boot_id=boot,validation_split=False)
        kept,refused=build_trial(candidates,raw)
        for k in range(len(kept)-1):
            kept[k],reason=extend(kept[k],kept[k+1],raw)
            if reason:raise ValueError(reason)
        for r in kept:
            response=[p for p in raw if p['seq'] in set(r['response_telemetry_seqs'])]
            lo,hi=audit['raw_stage_proof_t_us']
            if not lo<=r['t_state_us']<r['t_next_us']<=hi:raise ValueError('Missing raw stage proof')
            r.update(reference_response_schedule=[dict(telemetry_seq=p['seq'],elapsed_ms=p['elapsed_ms'],
                speed_ref=p['speed_ref']) for p in response],
                reference_step_crossed=any(p['speed_ref']!=r['state'][0] for p in response),
                exogenous_reference_contract='known MCU elapsed-time schedule; actual reference in every state and reward',
                environment_control_family=summary['environment_control_family'],
                saturation_ratio_basis='nominal-current boundary proxy, not measured Iq clamp occupancy')
        rows.extend(kept);rejected.extend(refused)
        sessions.append(dict(run_index=index,pair='binary-training',boot_id=boot,mode=trial['gain_mode'],
            firmware_id=trial['firmware_id'],validation_split=False,windows=len(kept)))
        rawhashes[str(path/'trial')]=digest
        for folder in ('trial','audit'):
            for f in (path/folder).glob('*.json*'):hashes[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
    validation=[r for r in rows if r['validation_split']];train=[r for r in rows if not r['validation_split']]
    if validation!=original_validation:raise ValueError('Validation data was changed')
    if not {r['boot_id'] for r in train}.isdisjoint({r['boot_id'] for r in validation}):raise ValueError('Boot leakage')
    out.mkdir(parents=True,exist_ok=False)
    blob=b''.join((json.dumps(r,allow_nan=False)+'\n').encode() for r in rows)
    (out/'response-windows.jsonl').write_bytes(blob)
    updated=dict(summary)
    updated.update(data_revision='handover-excitation-binary-train-v2',parent_dataset_sha256=summary['dataset_sha256'],
        dataset_sha256=hashlib.sha256(blob).hexdigest(),source_sessions=len(sessions),sessions=sessions,
        response_windows=len(rows),training_windows=len(train),validation_windows=len(validation),
        raw_telemetry_sha256=rawhashes,input_files_sha256=hashes,all_boot_ids=sorted(boots),
        validation_retained_byte_semantics=True,
        response_sample_count_histogram=dict(Counter(r['response_sample_count'] for r in rows)),
        observed_span_ms_range=[min(r['observed_response_span_ms'] for r in rows),max(r['observed_response_span_ms'] for r in rows)],
        transition_duration_ms_range=[min(r['transition_duration_ms'] for r in rows),max(r['transition_duration_ms'] for r in rows)],
        reference_step_crossing_windows=sum(r['reference_step_crossed'] for r in rows))
    write(out/'window-summary.json',updated);write(out/'rejected-new-groups.json',rejected)
    print(json.dumps(dict(train=len(train),validation=len(validation),dataset_sha256=updated['dataset_sha256'])))
    return updated


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','session','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.session,a.output)
