"""Audit/export factual command observations. No hardware or parameter identity claims."""
import argparse,bisect,csv,hashlib,json,math,struct
from pathlib import Path
from speedloop_stream_training import KI
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
f32=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]
def iq_command(packet):
    if not all(math.isfinite(packet[k]) for k in ('kp','error_history','integral_output')):raise ValueError('Nonfinite PI fields')
    return max(-3.,min(3.,f32(f32(packet['kp']*packet['error_history'])+packet['integral_output'])))
def export(replay,output):
    replay,output=map(Path,(replay,output));master=read(replay/'summary.json');assert master['passed']
    output.mkdir(parents=True,exist_ok=False);data=[];costs=[];inputs=[];seen=set();difference=[];spans=[]
    for entry in master['whole_boot_split']:
        folder=Path(entry['raw_folder']);summary=read(folder/'trial/summary.json');audit=read(folder/'full-hall-audit/summary.json');full=read(folder/'full-hall-audit/full-hall-edges.json')
        assert summary['passed'] and not summary['actor_applied'] and not summary['final_irq_fault'] and not summary['final_tx_fault']
        assert full['boot_id']==entry['boot_id'] and full['full_session_history'] and audit['passed'] and sha(folder/'stream/events.jsonl')==audit['hashes']['events.jsonl']
        assert entry['boot_id'] not in seen;seen.add(entry['boot_id'])
        events=[json.loads(line) for line in (folder/'stream/events.jsonl').read_text().splitlines()];packets=[e['packet'] for e in events if e['kind']=='telemetry']
        assert packets==[json.loads(line) for line in (folder/'trial/telemetry.jsonl').read_text().splitlines()]
        edges=full['records'];times=[r['t_us'] for r in edges]
        previous=None
        for p in packets:
            if not p['enabled'] or p['elapsed_ms']<3900:continue
            assert not p['fault'] and p['ki']==KI and math.isfinite(p['speed']) and p['applied_seq']
            at=bisect.bisect_right(times,p['t_us'])-1
            if at<6 or any(not e['valid'] or e['model_stage']!=4 for e in edges[at-6:at+1]):continue
            assert edges[at]['hall_code']==edges[at-6]['hall_code']
            assert all(b['edge']==a['edge']+1 and b['t_us']-a['t_us']==b['period_us'] for a,b in zip(edges[at-6:at],edges[at-5:at+1]))
            # Diagnostic causal speed over the last COMPLETE electrical Hall cycle.
            scale=sum(e['rpm']*e['period_us'] for e in edges[at-5:at+1])/6
            cycle=6*scale/(edges[at]['t_us']-edges[at-6]['t_us'])
            iq=iq_command(p);wrong=max(-3,min(3,f32(f32(p['kp']*(p['speed_ref']-p['speed']))+p['integral_output'])))
            difference.append(abs(iq-wrong));dt=0 if previous is None else p['t_us']-previous['t_us'];previous=p
            data.append(dict(Boot=entry['boot_id'],Split=entry['split'],Seq=p['seq'],TimeUs=p['t_us'],DtUs=dt,
                ElapsedMs=p['elapsed_ms'],ReferenceRpm=p['speed_ref'],RawSpeedRpm=p['speed'],CycleSpeedRpm=cycle,
                LastPIError=p['error_history'],IntegralA=p['integral_output'],Kp=p['kp'],Ki=p['ki'],IqCommandA=iq,
                NominalPhasePeakA=p['current'],BusV=p['vbus'],AppliedSeq=p['applied_seq'],ApplyUs=p['t_apply_us']))
        inputs.append(dict(boot=entry['boot_id'],split=entry['split'],telemetry_sha256=sha(folder/'trial/telemetry.jsonl'),Hall_sha256=sha(folder/'full-hall-audit/full-hall-edges.json')))
    for item in master['input_manifest']:
        assert sha(item['file'])==item['sha256'];w=read(item['file']);h=w['full_hall_reward'];span=w['measured_reward_span_us'];delta=w['physical_delta_action'][0]
        speed=h['mse_rpm2']/1e6;current=.3*(h['peak_nominal_current_a']/2)**2;over=.25*max(0,(h['peak_speed_rpm']-1500)/300)**2;sat=.25*h['saturation_fraction'];action=.0005*delta**2
        assert abs(w['time_scaled_reward']+sum((speed,current,over,sat))*span/100000+action)<1e-12
        costs.append(dict(Boot=w['boot_id'],Split=item['split'],PhysicalKey=w['physical_key'],SourceKp=w['state']['kp'],TargetKp=w['action_applied'][0],Switched=w['state']['kp']!=w['action_applied'][0],
            SpeedCost=speed,CurrentCost=current,OverspeedCost=over,SaturationCost=sat,ActionCost=action,SpanUs=span,DurationUs=w['duration_us'],RawMSE=h['mse_rpm2'],NominalPeakA=h['peak_nominal_current_a']))
        spans.append(span)
    for name,rows in [('observations',data),('reward-components',costs)]:
        with (output/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    report=dict(passed=True,boots=len(seen),rows=len(data),unique_reward_windows=len(costs),inputs=inputs,
        replay_sha256=sha(replay/'summary.json'),reward_decomposition_maximum_error_below=1e-12,
        command_formula='clamp(float32(kp*last_PI_boundary_error + integral_output), -3, 3)',
        Iq_reconstructed_from_actual_PI_fields=True,Iq_is_command_not_measured_current=True,
        between_telemetry_PI_commands_not_observed=True,independent_current_calibration=False,
        complete_cycle_speed_is_diagnostic_only=True,raw_Hall_primary_metric_unchanged=True,
        instantaneous_error_wrong_command_difference_max_A=max(difference),
        measured_reward_span_ms=[min(spans)/1000,sorted(spans)[len(spans)//2]/1000,max(spans)/1000],
        hardware_accessed=False,new_physical_trials=0,training_performed=False,actor_applied=False,deployment_allowed=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='inputs'}));return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',required=True);p.add_argument('--output',required=True);a=p.parse_args();export(a.replay,a.output)
