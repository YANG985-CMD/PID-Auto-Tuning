"""Replay only host-confirmed Hall records available at each real source state."""
import argparse,hashlib,json
from pathlib import Path

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())

def build(replay,audited_input,output):
    replay,audited_input,output=map(Path,(replay,audited_input,output))
    manifest=read(replay/'summary.json');assert manifest['passed'] and not output.exists()
    snapshots={};sources=[]
    for boot in manifest['whole_boot_split']:
        folder=Path(boot['raw_folder']);full_path=folder/'full-hall-audit/full-hall-edges.json'
        full=read(full_path);audit=read(folder/'full-hall-audit/summary.json')
        events_path=folder/'stream/events.jsonl'
        assert full['full_session_history'] and audit['passed'] and sha(events_path)==audit['hashes']['events.jsonl']
        known={}
        for line in events_path.read_text().splitlines():
            event=json.loads(line)
            if event['kind']!='telemetry':continue
            packet=event['packet'];capture=event['hall_capture']
            for record in capture['records']:
                assert full['records'][record['edge']-1]==record
                assert record['edge']<=capture['published_count']
                known[record['edge']]=record
            if not packet['enabled'] or packet['elapsed_ms']<3900:continue
            eligible=[r for r in known.values() if r['model_stage']==4 and r['t_us']<=packet['t_us']]
            if not eligible:raise ValueError('Source state has no host-confirmed causal Hall record')
            record=max(eligible,key=lambda r:r['t_us'])
            if not record['valid'] or record['hall_code'] not in range(1,7) or record['period_us']<=0:
                raise ValueError('Invalid source Hall measurement')
            snapshots[(packet['boot_id'],packet['seq'])]=(packet,record,capture['published_count'])
        sources.append(dict(boot_id=boot['boot_id'],events_file=str(events_path.resolve()),events_sha256=sha(events_path),
            full_Hall_file=str(full_path.resolve()),full_Hall_sha256=sha(full_path)))
    rows=[];keys=set()
    for item in manifest['input_manifest']:
        assert sha(item['file'])==item['sha256'];w=read(item['file']);state=w['state']
        packet,record,published=snapshots[(w['boot_id'],state['seq'])]
        assert state==packet and w['physical_key'] not in keys;keys.add(w['physical_key'])
        age=state['t_us']-record['t_us'];assert age>=0
        features=[float(record['hall_code']==code) for code in range(1,7)]+[age/20000,record['rpm']/1000]
        rows.append(dict(physical_key=w['physical_key'],split=item['split'],boot_id=w['boot_id'],
            source_seq=state['seq'],source_t_us=state['t_us'],confirmed_published_count=published,
            source_Hall_record=record,Hall_age_us=age,features=features))
    report=dict(passed=True,profile='host-confirmed-causal-Hall-sector-age-rpm-v1',
        audited_input_sha256=sha(audited_input),replay_summary_sha256=sha(replay/'summary.json'),
        rows=rows,sources=sources,unique_windows=len(rows),
        feature_names=[f'last_confirmed_Hall_code_{c}' for c in range(1,7)]+['confirmed_Hall_age_over_20ms','confirmed_Hall_rpm_over_1000'],
        maximum_Hall_age_us=max(r['Hall_age_us'] for r in rows),
        future_Hall_records_used=False,unconfirmed_past_Hall_records_used=False,
        full_trace_used_for_readback_verification_only=True,weights_fit=False,
        primary_raw_Hall_reward_changed=False,Actor_input_contract_changed=False,
        hardware_accessed=False,actor_applied=False,candidate_admission=False,
        deployment_allowed=False,performance_claim_allowed=False)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','sources')}));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('replay','audited-input','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();build(a.replay,a.audited_input,a.output)
