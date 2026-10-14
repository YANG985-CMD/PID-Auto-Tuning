"""Strict real replay from matched v11/v12 controls and complete-pair splits.

Known MCU reference schedule and elapsed time are part of the environment.
Rewards use each response packet's actual reference, including step crossings.
No interpolation, duplicate frames, old-controller pooling, or hardware access.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from speedloop_response_windows import lines,write,build_trial
from stitch_speedloop_replay import extend
from speedloop_excitation_review import reference_matches,REFERENCE_SCHEDULE
from speedloop_handover_excitation import IDENTITY as V11,IMAGE_SHA as SHA11
from speedloop_excitation_evidence import IDENTITY as V12,IMAGE_SHA as SHA12


def verified_round(path,seen_boots,seen_hashes):
    trial=json.loads((path/'trial/summary.json').read_text(encoding='utf-8'))
    audit=json.loads((path/'audit/analysis.json').read_text(encoding='utf-8'))
    if not (trial['passed'] and audit['passed'] and trial['final_irq_fault']==trial['final_tx_fault']==0
            and all(trial[k] for k in ('protocol_stop_acknowledged','core_halted_after_physical_shutdown',
                                      'can_released_after_shutdown'))):
        raise ValueError('Faulted or incompletely stopped physical trial')
    expected={V11:SHA11,V12:SHA12}
    if trial['firmware_id'] not in expected or trial['bin_sha256']!=expected[trial['firmware_id']]:
        raise ValueError('Do not pool different handover controls')
    if trial['reference_schedule_ms_rpm']!=REFERENCE_SCHEDULE or trial['actor_applied']:
        raise ValueError('Unreviewed physical environment')
    raw=lines(path/'trial/telemetry.jsonl')
    digest=hashlib.sha256((path/'trial/telemetry.jsonl').read_bytes()).hexdigest()
    boot=raw[0]['boot_id']
    if boot in seen_boots or digest in seen_hashes:
        raise ValueError('Duplicate boot/telemetry')
    seen_boots.add(boot);seen_hashes.add(digest)
    if not all(r['boot_id']==boot and (not r['enabled'] or reference_matches(r['elapsed_ms'],r['speed_ref'])) for r in raw):
        raise ValueError('Bad boot or reference schedule')
    return trial,audit,raw,boot,digest


def run(development,cohort,output):
    development,cohort,out=map(lambda x:Path(x).resolve(),(development,cohort,output))
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    contract=json.loads((cohort/'session-summary.json').read_text(encoding='utf-8'))
    if not contract['passed'] or contract['new_training_pairs']!=[1,2] or contract['new_validation_pairs']!=[3]:
        raise ValueError('Incomplete cohort or changed predeclared split')
    paths=[(p,False,'development') for p in sorted(development.glob('round-*'))]
    if len(paths)!=2:raise ValueError('Expected completed development pair')
    for pair in range(1,4):
        rounds=sorted((cohort/f'pair-{pair:02d}').glob('round-*'))
        if len(rounds)!=2:raise ValueError('Missing physical round')
        paths.extend((p,pair==3,f'cohort-pair-{pair:02d}') for p in rounds)
    boots=set();digests=set();rows=[];rejected=[];sessions=[];rawhashes={};inputhashes={}
    for index,(path,validation,pair) in enumerate(paths,1):
        trial,audit,raw,boot,digest=verified_round(path,boots,digests)
        candidates=[r for r in lines(path/'audit/experience-candidates.jsonl')
                    if r['stage_confirmed_from_raw_edges'] and r['state'][9]>=3900]
        for r in candidates:r.update(run_index=index,boot_id=boot,validation_split=validation)
        kept,refused=build_trial(candidates,raw)
        for k in range(len(kept)-1):
            kept[k],reason=extend(kept[k],kept[k+1],raw)
            if reason:raise ValueError(reason)
        for r in kept:
            response=[p for p in raw if p['seq'] in set(r['response_telemetry_seqs'])]
            lo,hi=audit['raw_stage_proof_t_us']
            if not lo<=r['t_state_us']<r['t_next_us']<=hi:raise ValueError('Unproven stage')
            schedule=[dict(telemetry_seq=p['seq'],elapsed_ms=p['elapsed_ms'],speed_ref=p['speed_ref']) for p in response]
            r.update(reference_response_schedule=schedule,
                reference_step_crossed=any(p['speed_ref']!=r['state'][0] for p in response),
                exogenous_reference_contract='known MCU elapsed-time schedule; actual reference in every state and reward',
                environment_control_family='v10-handover-v8-excitation',
                saturation_ratio_basis='nominal-current boundary proxy, not measured Iq clamp occupancy')
        used=[seq for r in kept for seq in r['response_telemetry_seqs']]
        if len(used)!=len(set(used)):raise ValueError('Overlapping responses')
        rows.extend(kept);rejected.extend(refused)
        rawhashes[str(path/'trial')]=digest
        for name in ('trial/telemetry.jsonl','trial/commands.jsonl','trial/hall-edges.json',
                     'trial/raw-can.jsonl','trial/summary.json','audit/analysis.json','audit/experience-candidates.jsonl'):
            f=path/name
            if f.exists():inputhashes[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
        sessions.append(dict(run_index=index,pair=pair,boot_id=boot,mode=trial['gain_mode'],
            firmware_id=trial['firmware_id'],validation_split=validation,windows=len(kept)))
    train=[r for r in rows if not r['validation_split']];val=[r for r in rows if r['validation_split']]
    if not {r['boot_id'] for r in train}.isdisjoint({r['boot_id'] for r in val}):raise ValueError('Boot leakage')
    if not all(r['action_applied'][1]==.0014400000218302011 and r['action_normalized'][1]==0 for r in rows):
        raise ValueError('Ki must remain fixed')
    out.mkdir(parents=True,exist_ok=False)
    blob=b''.join((json.dumps(r,allow_nan=False)+'\n').encode() for r in rows)
    (out/'response-windows.jsonl').write_bytes(blob)
    report=dict(schema_version=1,source='real_motor',hardware_accessed=False,
        data_revision='handover-excitation-complete-pair-v1',environment_control_family='v10-handover-v8-excitation',
        older_handover_controls_excluded=True,source_sessions=len(paths),sessions=sessions,
        response_windows=len(rows),training_windows=len(train),validation_windows=len(val),
        replay_warmup_required=128,training_ready=len(train)>=128 and bool(val),
        replay_count_ready=len(train)>=128 and bool(val),action_mask=[1,0],fixed_ki=.0014400000218302011,
        minimum_response_samples=4,minimum_observed_span_ms=60,minimum_source_elapsed_ms=3900,
        window_profile='strict',exploratory_only=False,variable_duration_native_training_admitted=True,
        discount_contract='gamma 0.99 per grouped decision; state includes elapsed time',
        validation_run_indices=[s['run_index'] for s in sessions if s['validation_split']],
        split_unit='complete physical pairs and boot sessions',all_boot_ids=sorted(boots),
        raw_telemetry_sha256=rawhashes,input_files_sha256=inputhashes,
        dataset_sha256=hashlib.sha256(blob).hexdigest(),reference_schedule_ms_rpm=REFERENCE_SCHEDULE,
        response_sample_count_histogram=dict(Counter(r['response_sample_count'] for r in rows)),
        observed_span_ms_range=[min(r['observed_response_span_ms'] for r in rows),max(r['observed_response_span_ms'] for r in rows)],
        transition_duration_ms_range=[min(r['transition_duration_ms'] for r in rows),max(r['transition_duration_ms'] for r in rows)],
        reference_step_crossing_windows=sum(r['reference_step_crossed'] for r in rows),
        action_support='Absolute Kp targets baseline and +4%; physical negative deltas only return to baseline',
        td3_training_performed=False,deployment_allowed=False,performance_claim_allowed=False,
        ordinary_live_admission=False,thermal_gate_modified=False)
    write(out/'window-summary.json',report);write(out/'rejected-groups.json',rejected)
    print(json.dumps({k:report[k] for k in ('training_windows','validation_windows','dataset_sha256','training_ready')}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('development','cohort','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.development,a.cohort,a.output)
