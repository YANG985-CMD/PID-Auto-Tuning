"""Merge immutable live Hall records with the halted tail and audit every edge."""
import argparse
import hashlib
import json
from pathlib import Path

def merge(folder,output):
    folder,output=Path(folder),Path(output)
    summary=json.loads((folder/'trial/summary.json').read_text(encoding='utf-8'))
    tail=json.loads((folder/'trial/hall-edges.json').read_text(encoding='utf-8'))
    if (not summary['passed'] or not summary['protocol_stop_acknowledged'] or summary['final_irq_fault']
        or summary['final_tx_fault'] or not summary['core_halted_after_physical_shutdown']
        or not summary['can_released_after_shutdown'] or not summary.get('live_hall_capture')):
        raise ValueError('Full Hall capture requires complete stopped physical trial')
    byindex={};published=0;read_times=[];boot=None;packet_count=0
    profile=summary.get('hall_read_profile',summary.get('stream',{}).get('hall_read_profile','immediate-v1'))
    if profile not in ('immediate-v1','pipelined-v1','pipelined-chunk8-v2'):raise ValueError('Unknown Hall read proof profile')
    previous_observed=previous_start=0
    previous_staged=0
    for line in (folder/'stream/events.jsonl').read_text(encoding='utf-8').splitlines():
        e=json.loads(line)
        if e['kind']!='telemetry':continue
        packet_count+=1;b=e['packet']['boot_id']
        if boot is None:boot=b
        if boot!=b:raise ValueError('Mixed physical boots')
        c=e.get('hall_capture')
        if c is None:raise ValueError('Missing live capture at a telemetry packet')
        if not 0<=c['read_ms']<=6:raise ValueError('Live capture exceeded reserved time')
        rows=c['records'];end=c['published_count']
        if profile=='pipelined-v1':
            observed=c.get('observed_published_count',-1)
            if (c.get('confirmation')!='next-counter-before-commit-v1' or end!=previous_observed
                or not previous_observed<=observed<=previous_observed+64
                or observed-previous_start>tail['capacity']):
                raise ValueError('Deferred Hall publication lacks intact next-counter proof')
            previous_start,previous_observed=previous_observed,observed
        elif profile=='pipelined-chunk8-v2':
            observed=c.get('observed_published_count',-1)
            start=c.get('read_start_cursor',-1);staged=c.get('read_end_cursor',-1)
            if (c.get('confirmation')!='next-counter-before-commit-v1' or end!=previous_staged
                or start!=previous_staged or not previous_observed<=observed
                or not start<=staged<=min(observed,start+8,start+tail['capacity']-start%tail['capacity'])
                or not 0<=observed-start<=64 or observed-previous_start>tail['capacity']):
                raise ValueError('Bounded Hall publication lacks intact next-counter proof')
            details=c.get('read_details',{})
            if (details.get('block_records')!=staged-start or details.get('remaining_backlog')!=observed-staged
                or details.get('read_ms')!=c['read_ms']):raise ValueError('Hall read detail mismatch')
            previous_start,previous_observed,previous_staged=start,observed,staged
        if [r['edge'] for r in rows]!=list(range(published+1,end+1)):
            raise ValueError('Live Hall gap, duplicate or publication count mismatch')
        for r in rows:byindex[r['edge']]=r
        published=end;read_times.append(c['read_ms'])
    overlap=0
    for row in tail['records']:
        n=row['edge']
        if n in byindex:
            if byindex[n]!=row:raise ValueError('Live data differs from actual halted Hall ring')
            overlap+=1
        else:byindex[n]=row
    total=tail['total_edges']
    if sorted(byindex)!=list(range(1,total+1)):raise ValueError('Full session Hall history incomplete')
    records=[byindex[i] for i in sorted(byindex)]
    for a,b in zip(records,records[1:]):
        if b['t_us']<=a['t_us'] or b['t_us']-a['t_us']!=b['period_us']:
            raise ValueError('Hall clock/period mismatch')
    if any(not r['valid'] or r['period_us']<=0 for r in records if r['model_stage']==4):
        raise ValueError('Invalid RunStage Hall sample')
    output.mkdir(parents=True,exist_ok=False)
    trace=dict(total_edges=total,capacity=tail['capacity'],records=records,
        full_session_history=True,boot_id=boot,source='live-read-only-ring-plus-exact-halted-tail')
    (output/'full-hall-edges.json').write_text(json.dumps(trace,indent=2)+'\n',encoding='utf-8')
    result=dict(passed=True,boot_id=boot,total_actual_edges=total,live_edges=published,hall_read_profile=profile,
        halted_tail_overlap_verified=overlap,tail_completion_edges=total-published,
        complete_telemetry_packets=packet_count,maximum_read_ms=max(read_times),
        mean_read_ms=sum(read_times)/len(read_times),hardware_written=False,
        gain_exploration=summary.get('gain_exploration',summary.get('continuous_upper8_experimental_probe',False))
            or len(summary.get('gain_pairs',[]))>1,training_performed=False,actor_applied=False,
        deployment_allowed=False,performance_claim_allowed=False,
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (folder/'stream/events.jsonl',folder/'trial/hall-edges.json')})
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('folder','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();merge(a.folder,a.output)
