"""Causal observation ablation from immutable, independently audited records."""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from audit_speedloop_snapshot_timing import capture_origin,snapshot_interval

PROFILE='causal-six-period-Hall-sector-v1'
CODES=(6,2,3,1,5,4)
FEATURES=('speed_ref','causal_six_period_speed','causal_six_period_error',
    'previous_telemetry_causal_six_period_error','integral_output','nominal_current',
    'vbus','actual_kp','Hall_sector_sin','Hall_sector_cos')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(replay,output):
    replay,output=map(Path,(replay,output));source=json.loads((replay/'summary.json').read_text())
    assert source['passed'] and source['split_frozen_before_gradients']
    assert source['action_mask']==[1,0] and not source['old_replay_appended']
    output.mkdir(parents=True,exist_ok=False);boots={};rows=[];keys=set()
    for item in source['input_manifest']:
        assert sha(item['file'])==item['sha256']
        window=json.loads(Path(item['file']).read_text())
        assert window['physical_key'] not in keys;keys.add(window['physical_key'])
        folder=Path(item['raw_window_file']).parent.parent
        if folder not in boots:
            packets=[json.loads(v) for v in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
            hall=folder/'full-hall-audit/full-hall-edges.json'
            assert sha(hall)==window['full_hall_reward']['full_hall_sha256']
            records=json.loads(hall.read_text())['records']
            records=[r for r in records if r['model_stage']==4]
            assert all(r['valid'] and r['period_us']>0 for r in records)
            assert all(b['edge']==a['edge']+1 and b['t_us']-a['t_us']==b['period_us']
                and CODES[(CODES.index(a['hall_code'])+1)%6]==b['hall_code']
                for a,b in zip(records,records[1:]))
            boots[folder]=(capture_origin(packets),records,[r['t_us'] for r in records],sha(hall))
        origin,records,times,hallsha=boots[folder]

        def feature(history):
            speeds=[];proof=[]
            for packet in history[-2:]:
                lo,hi=snapshot_interval(packet,origin)
                index=bisect.bisect_right(times,lo)-1
                assert index>=5
                six=records[index-5:index+1]
                assert len({r['hall_code'] for r in six})==6
                assert all(r['t_us']<=lo for r in six)
                speed=30000000/sum(r['period_us'] for r in six)
                assert speed>0 and all(r['rpm']>0 for r in six)
                speeds.append(speed)
                proof.append(dict(packet_seq=packet['seq'],snapshot_lower_us=lo,snapshot_upper_us=hi,
                    last_used_edge=six[-1]['edge'],last_used_edge_us=six[-1]['t_us'],
                    six_completed_periods_us=[r['period_us'] for r in six],
                    last_used_hall_code=six[-1]['hall_code'],causal_speed_rpm=speed))
            p=history[-1];phase=2*math.pi*CODES.index(records[index]['hall_code'])/6
            vector=[p['speed_ref']/1000,speeds[-1]/1000,(p['speed_ref']-speeds[-1])/1000,
                (history[-2]['speed_ref']-speeds[-2])/1000,p['integral_output']/3,
                p['current']/2,p['vbus']/24,p['kp']/.003389,math.sin(phase),math.cos(phase)]
            assert all(math.isfinite(v) and abs(v)<=5 for v in vector)
            return vector,proof

        raw,proof=feature(window['state_history']);next_raw,next_proof=feature(window['response'][-3:])
        rows.append(dict(physical_key=window['physical_key'],boot_id=window['boot_id'],split=item['split'],
            features=raw,next_features=next_raw,state_proof=proof,next_state_proof=next_proof,
            original_replay_window_sha256=item['sha256'],original_replay_window=item['file'],
            full_hall_sha256=hallsha,full_hall_file=str((folder/'full-hall-audit/full-hall-edges.json').resolve())))
    report=dict(passed=True,observation_profile=PROFILE,feature_names=FEATURES,rows=rows,
        unique_windows=len(rows),whole_boot_split=source['whole_boot_split'],
        normalized_gain_scale_kp=source['normalized_gain_scale_kp'],
        source_replay_summary_sha256=sha(replay/'summary.json'),
        no_future_edges_used=True,completed_periods_only=True,Hall_sector_is_not_continuous_rotor_angle=True,
        original_state_and_next_state_timestamps_unchanged=True,physical_rewards_unchanged=True,
        physical_actions_unchanged=True,physical_split_unchanged=True,
        primary_metric_unchanged=True,hardware_feedback_changed=False,
        hardware_accessed=False,training_performed=False,deployment_allowed=False,performance_claim_allowed=False)
    path=output/'observation-view.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','whole_boot_split')}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();build(a.replay,a.output)
