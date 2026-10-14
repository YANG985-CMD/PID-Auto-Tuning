"""Measured source-gain/action support; do not infer unobserved motor outcomes."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path


def audit(replay,cohort,output):
    source_path=Path(replay)/'summary.json';source=json.loads(source_path.read_text())
    selected=json.loads(Path(cohort).read_text())
    assert source['passed'] and selected['passed']
    assert selected['source_replay_summary_sha256']==hashlib.sha256(source_path.read_bytes()).hexdigest()
    membership={r['physical_key']:r['selected_for_matched_steady_cohort'] for r in selected['eligibility']}
    groups=defaultdict(Counter);seen=set()
    for item in source['input_manifest']:
        path=Path(item['file']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        r=json.loads(path.read_text());key=r['physical_key'];assert key not in seen;seen.add(key)
        source_gain=r['state']['kp'];actual=r['action_applied'][0]
        assert actual==r['response'][0]['kp'] and r['state']['ki']==r['action_applied'][1]
        groups[(item['split'],'all')][(source_gain,actual)]+=1
        if membership[key]:groups[(item['split'],'steady')][(source_gain,actual)]+=1
    rows=[]
    for (split,cohort_name),counts in groups.items():
        total=sum(counts.values());switching=sum(n for (old,new),n in counts.items() if old!=new)
        rows.append(dict(split=split,cohort=cohort_name,total_windows=total,
            actual_gain_switch_windows=switching,holding_windows=total-switching,
            actual_gain_switch_fraction=switching/total,
            measured_source_gain_to_action_counts=[dict(source_kp=a,actual_action_kp=b,windows=n)
                for (a,b),n in sorted(counts.items())]))
    report=dict(passed=True,unique_windows=len(seen),support=rows,
        off_diagonal_measured_support_only=True,unmeasured_counterfactuals_not_counted=True,
        hardware_accessed=False,training_performed=False,candidate_admission=False,
        deployment_allowed=False,performance_claim_allowed=False,
        source_manifest_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())
    assert not Path(output).exists();Path(output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('replay','cohort','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();audit(a.replay,a.cohort,a.output)
