"""Summarize only complete actual-gain plateaus, distinct physical boots."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


def metrics(rows):
    return dict(kp=rows[0]['kp'],plateau_count=len(rows),
        full_hall_rmse_rpm=math.sqrt(sum(r['full_Hall_hold_diagnostic_rmse_rpm']**2 for r in rows)/len(rows)),
        mean_peak_nominal_current_a=sum(r['nominal_peak_current_a'] for r in rows)/len(rows),
        mean_peak_full_hall_speed_rpm=sum(r['full_Hall_peak_speed_rpm'] for r in rows)/len(rows))


def comparison(group,performance_eligible=True):
    base=group['0'];result={}
    for key,row in group.items():
        if key=='0':continue
        improvement=100*(1-row['full_hall_rmse_rpm']/base['full_hall_rmse_rpm'])
        result[key]=dict(rmse_improvement_percent=improvement,
            peak_current_change_percent=100*(row['mean_peak_nominal_current_a']/base['mean_peak_nominal_current_a']-1),
            descriptive_gate_passed=performance_eligible and improvement>=5 and row['mean_peak_nominal_current_a']<=base['mean_peak_nominal_current_a']
                and row['mean_peak_full_hall_speed_rpm']<=base['mean_peak_full_hall_speed_rpm'])
    return result


def summarize(folders,output):
    allrows=defaultdict(list);boots=[];byboot=[];hashes={};eligibility=[]
    for raw in folders:
        folder=Path(raw);legacy=json.loads((folder/'plateaus.json').read_text(encoding='utf-8'))
        full=json.loads((folder/'full-hall-score.json').read_text(encoding='utf-8'))
        summary=json.loads((folder/'trial/summary.json').read_text(encoding='utf-8'))
        if (not summary['passed'] or not full['passed'] or full['boot_id'] in boots
            or full['boot_id']!=legacy['boot_id'] or summary['final_irq_fault'] or summary['final_tx_fault']
            or not summary['protocol_stop_acknowledged'] or not summary['core_halted_after_physical_shutdown']
            or not summary['can_released_after_shutdown']):raise ValueError('Incomplete or duplicate physical trial')
        boots.append(full['boot_id']);byslot={r['slot']:r for r in legacy['plateaus']};groups=defaultdict(list)
        eligible=not legacy.get('transient_response_audit',False);eligibility.append(eligible)
        for row in full['plateaus']:
            if not row['full_Hall_covered']:raise ValueError('Incomplete Hall scoring span')
            old=byslot[row['slot']];level=str(old['level'])
            value=dict(row,nominal_peak_current_a=old['peak_nominal_current_a'])
            groups[level].append(value);allrows[level].append(value)
        scores={key:metrics(rows) for key,rows in groups.items()}
        byboot.append(dict(folder=str(folder.resolve()),boot_id=full['boot_id'],metrics=scores,
            performance_evaluation_eligible=eligible,comparisons=comparison(scores,eligible)))
        for name in ('plateaus.json','full-hall-score.json','trial/summary.json'):
            path=folder/name;hashes[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
    scores={key:metrics(rows) for key,rows in allrows.items()};replicated={}
    for level in scores:
        if level=='0':continue
        replicated[level]=len(boots)>=2 and all(level in row['comparisons'] and row['comparisons'][level]['descriptive_gate_passed'] for row in byboot)
    result=dict(passed=True,unique_boots=boots,metrics=scores,comparisons=comparison(scores,all(eligibility)),by_boot=byboot,
        performance_evaluation_eligible=all(eligibility),
        replicated_behavior_probe_gate=replicated,frozen_actor_performance_verified=False,
        primary_metric_version='raw-Hall-held-time-integral-v1',candidate_admission=False,
        actor_applied=False,training_performed=False,deployment_allowed=False,performance_claim_allowed=False,
        mean_peak_current_is_nominal=True,independent_speed_ground_truth=False,hashes=hashes)
    Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('by_boot','hashes')}));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folders',nargs='+',required=True)
    p.add_argument('--output',required=True);a=p.parse_args();summarize(a.folders,a.output)
