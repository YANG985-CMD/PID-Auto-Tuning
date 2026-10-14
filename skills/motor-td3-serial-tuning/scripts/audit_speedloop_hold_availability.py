"""Inspect stable actual gain/reference spans before changing replay horizons.

Counts are optimistic availability, not audited source/ACK/response experiences.
No raw data, reward, split, controller or training gate is changed.
"""
import argparse,collections,hashlib,json,struct
from pathlib import Path
from speedloop_stream_training import CausalStream
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def audit(replay,output,horizon_us):
    replay,output=Path(replay),Path(output)
    if output.exists() or horizon_us not in (500000,1000000):raise ValueError('One-use predeclared diagnostic horizon required')
    master=read(replay/'summary.json');assert master['passed'] and master['stream_gain_profile']=='bidirectional16-upper8-fullhall'
    groups=collections.defaultdict(lambda:dict(windows=0,boots=set(),spans=0))
    rows=[];sources=[];seen=set()
    for entry in master['whole_boot_split']:
        folder=Path(entry['raw_folder']);s=read(folder/'trial/summary.json');h=read(folder/'full-hall-audit/summary.json')
        assert s['passed'] and s['final_irq_fault']==s['final_tx_fault']==0 and not s['actor_applied']
        assert s['protocol_stop_acknowledged'] and s['core_halted_after_physical_shutdown'] and s['can_released_after_shutdown']
        eventpath=folder/'stream/events.jsonl';assert sha(eventpath)==h['hashes']['events.jsonl']
        assert entry['boot_id']==h['boot_id'] and entry['boot_id'] not in seen;seen.add(entry['boot_id'])
        block=[]
        def finish():
            if not block:return
            first,last=block[0],block[-1]
            # Deliberately overcount by one per eligible stable span. Exact
            # state history, source/ACK, window spacing and Hall validation
            # can only reduce this availability; these are not replay rows.
            duration=last['t_us']-first['t_us']
            available=duration//horizon_us+1 if duration>=horizon_us else 0
            if not available:return
            key=(entry['split'],first['kp']);g=groups[key]
            g['windows']+=available;g['boots'].add(entry['boot_id']);g['spans']+=1
            rows.append(dict(boot_id=entry['boot_id'],split=entry['split'],actual_kp=first['kp'],
                actual_reference_rpm=first['speed_ref'],begin_us=first['t_us'],end_us=last['t_us'],
                retained_packets=len(block),optimistic_nonoverlapping_windows=available))
        for line in eventpath.read_text(encoding='utf-8').splitlines():
            e=json.loads(line)
            if e['kind']!='telemetry':continue
            p=e['packet'];valid=p['enabled'] and p['applied_seq'] and CausalStream.valid_stage(e['stage_proof'],p)
            if not valid:finish();block=[];continue
            assert p['boot_id']==entry['boot_id'] and not p['fault']
            if block and (p['kp']!=block[-1]['kp'] or p['ki']!=block[-1]['ki'] or p['speed_ref']!=block[-1]['speed_ref']
                or p['seq']!=block[-1]['seq']+1 or not 15000<=p['t_us']-block[-1]['t_us']<=25000):
                finish();block=[]
            block.append(p)
        finish();sources.append(dict(boot_id=entry['boot_id'],split=entry['split'],journal=str(eventpath),sha256=sha(eventpath)))
    counts=[dict(split=s,actual_kp=k,optimistic_nonoverlapping_windows=g['windows'],independent_boots=len(g['boots']),actual_stable_spans=g['spans'])
            for (s,k),g in sorted(groups.items())]
    # Same nine held targets as prepareMotorBidirectionalSwitchSampler.
    # The four odd positive bridge levels are allowed interpolation, not
    # additional held targets required by the existing training sampler.
    f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
    targets=list(map(f32,(.002856927,.002989098,.003121269,.00325344,.003389,.00345678,.00352456,.00359234,.00366012)))
    lookup={(r['split'],r['actual_kp']):r for r in counts}
    missing=[]
    for k in targets:
        r=lookup.get(('train',k),{})
        if r.get('optimistic_nonoverlapping_windows',0)<32 or r.get('independent_boots',0)<2:
            missing.append(dict(actual_kp=k,optimistic_training_windows=r.get('optimistic_nonoverlapping_windows',0),
                training_boots=r.get('independent_boots',0)))
    report=dict(passed=True,diagnostic_horizon_us=horizon_us,source_replay_sha256=sha(replay/'summary.json'),
        independent_physical_boots=len(seen),counts=counts,missing_existing_balanced_hold_support=missing,
        existing_nine_held_targets=targets,optimistic_counting_rule='floor(span/horizon)+1 for spans at least horizon long',
        optimistic_hold_gate_met=not missing,exact_command_ACK_reconstruction_still_required=True,
        switching_support_not_evaluated=True,counts_are_not_training_experiences=True,
        rows=rows,sources=sources,hardware_accessed=False,new_motor_trials=0,
        physical_actions_rewards_and_primary_metric_unchanged=True,training_performed=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','sources','counts')}));return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    p.add_argument('--horizon-us',required=True,type=int,choices=(500000,1000000));a=p.parse_args();audit(a.replay,a.output,a.horizon_us)
