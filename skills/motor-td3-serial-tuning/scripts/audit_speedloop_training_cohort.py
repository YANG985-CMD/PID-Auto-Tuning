"""Classify immutable windows against the predeclared steady scoring spans."""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin,snapshot_interval


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(replay,output):
    source=Path(replay)/'summary.json';manifest=json.loads(source.read_text())
    assert manifest['passed'] and manifest['split_frozen_before_gradients']
    cache={};groups=defaultdict(list);eligibility=[];keys=set()
    for item in manifest['input_manifest']:
        assert sha(item['file'])==item['sha256']
        w=json.loads(Path(item['file']).read_text());folder=Path(item['raw_window_file']).parent.parent
        assert w['physical_key'] not in keys;keys.add(w['physical_key'])
        if folder not in cache:
            packets=[json.loads(v) for v in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
            path=folder/'plateaus.json';score=json.loads(path.read_text());assert score['passed']
            cache[folder]=(capture_origin(packets),score['plateaus'],str(path.resolve()),sha(path),bool(score.get('transient_response_audit',False)))
        origin,plateaus,scorepath,scorehash,is_transient=cache[folder]
        lo=snapshot_interval(w['state_history'][0],origin)[0]
        hi=snapshot_interval(w['response'][-1],origin)[1]
        matched=[p for p in plateaus if w['state']['kp']==p['kp']==w['action_applied'][0]
            and lo>=origin+1000*p['analysis_start_ms'] and hi<=origin+1000*p['analysis_end_ms']]
        assert len(matched)<=1
        row=dict(physical_key=w['physical_key'],split=item['split'],boot_id=w['boot_id'],
            selected_for_matched_steady_cohort=bool(matched) and not is_transient,kp=w['action_applied'][0],
            matched_actual_response_interval=bool(matched),response_interval_kind='transient' if is_transient else 'steady',
            full_hall_window_mse_rpm2=w['full_hall_reward']['mse_rpm2'],
            reward=w['time_scaled_reward'],source_elapsed_ms=w['state']['elapsed_ms'],
            original_replay_window=item['file'],original_replay_window_sha256=item['sha256'],
            source_plateau_analysis=scorepath,source_plateau_analysis_sha256=scorehash,
            clock_origin_us=origin,snapshot_lower_us=lo,snapshot_upper_us=hi,
            selected_plateau_slot=matched[0]['slot'] if matched else -1)
        eligibility.append(row);groups[(item['split'],w['action_applied'][0],row['selected_for_matched_steady_cohort'])].append(row)
    stats=[]
    for (split,kp,selected),items in groups.items():
        stats.append(dict(split=split,kp=kp,predeclared_steady_span=selected,window_count=len(items),
            pooled_window_RMSE_rpm=math.sqrt(sum(r['full_hall_window_mse_rpm2'] for r in items)/len(items)),
            mean_window_reward=sum(r['reward'] for r in items)/len(items)))
    report=dict(passed=True,all_original_experiences_retained=True,
        selection_uses_predeclared_actual_plateau_analysis_spans=True,
        source_and_next_state_history_and_response_inside_same_actual_gain_plateau=True,
        source_replay_summary_sha256=sha(source),unique_original_windows=len(eligibility),
        selected_counts={s:sum(r['split']==s and r['selected_for_matched_steady_cohort'] for r in eligibility)
            for s in ('train','validation')},statistics=stats,eligibility=eligibility,
        training_performed=False,hardware_accessed=False,deployment_allowed=False,performance_claim_allowed=False)
    assert not Path(output).exists();Path(output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='eligibility'}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();inspect(a.replay,a.output)
