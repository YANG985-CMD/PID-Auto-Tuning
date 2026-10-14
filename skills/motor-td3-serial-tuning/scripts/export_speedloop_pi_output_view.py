"""Versioned PI-command observations from immutable actual motor windows.

Iq is the command at the last PI boundary, not an independently measured current.
This view cannot be used by the old live observation builder.
"""
import argparse, hashlib, json, math, struct
from pathlib import Path

PROFILE = 'history20-40-PI-command-v1'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
f32 = lambda v: struct.unpack('<f', struct.pack('<f', v))[0]

def command(packet):
    required = ('kp','error_history','integral_output')
    if not all(math.isfinite(packet[k]) for k in required):
        raise ValueError('Missing or nonfinite actual PI fields')
    return max(-3.,min(3.,f32(f32(packet['kp']*packet['error_history'])+packet['integral_output'])))

def export(replay, output):
    replay, output = Path(replay), Path(output)
    master = read(replay/'summary.json')
    if not master['passed'] or master['action_coordinate_version'] != 'absolute-target-bidirectional16-upper8-scale0p00054224-v7':
        raise ValueError('Only the audited, frozen v7 replay is supported')
    if output.exists(): raise ValueError('One-use output already exists')
    rows=[];keys=set();splitBoots={'train':set(),'validation':set()};wrong=[]
    for item in master['input_manifest']:
        path=Path(item['file'])
        if sha(path)!=item['sha256']: raise ValueError('Immutable replay hash mismatch')
        w=read(path);key=w['physical_key'];split=item['split']
        if key in keys or split not in splitBoots or w['split']!=split:
            raise ValueError('Duplicate physical key or split mismatch')
        keys.add(key);splitBoots[split].add(w['boot_id'])
        s=w['state_history'][-1];n=w['response'][-1]
        if s!=w['state'] or not s['t_us']<n['t_us'] or s['boot_id']!=n['boot_id'] or s['boot_id']!=w['boot_id']:
            raise ValueError('Ambiguous state or next-state source')
        if any(p['fault'] or not p['enabled'] or p['ki']!=f32(.00144) for p in (s,n)):
            raise ValueError('Invalid physical PI source')
        values=[command(s),command(n)]
        for p,v in zip((s,n),values):
            instant=max(-3.,min(3.,f32(f32(p['kp']*(p['speed_ref']-p['speed']))+p['integral_output'])))
            wrong.append(abs(instant-v))
        rows.append(dict(physical_key=key,boot_id=w['boot_id'],split=split,
            original_window_file=str(path),original_window_sha256=item['sha256'],
            source_packet_seq=s['seq'],next_packet_seq=n['seq'],source_packet_t_us=s['t_us'],next_packet_t_us=n['t_us'],
            source_Iq_command_A=values[0],next_Iq_command_A=values[1],
            source_feature=f32(values[0]/3),next_feature=f32(values[1]/3)))
    if splitBoots['train'] & splitBoots['validation']: raise ValueError('Boot split leakage')
    if len(rows)!=master['total_unique_windows']:raise ValueError('Missing replay rows')
    report=dict(passed=True,observation_profile=PROFILE,unique_windows=len(rows),rows=rows,
        train_boots=sorted(splitBoots['train']),validation_boots=sorted(splitBoots['validation']),
        source_replay_sha256=sha(replay/'summary.json'),
        changed_input_column=10,removed_input='masked elapsed time',added_input='last PI boundary reconstructed Iq command / 3A',
        source_and_next_features_use_only_their_respective_actual_packets=True,
        feature_formula='float32(clamp(float32(float32(kp*error_history)+integral_output),-3,3)/3)',
        Iq_is_command_not_measured_current=True,maximum_wrong_instantaneous_error_command_difference_A=max(wrong),
        physical_actions_unchanged=True,physical_rewards_unchanged=True,physical_split_unchanged=True,
        previous_observation_builder_runtime_compatible=False,Ki_fixed=.00144,action_mask=[1,0],
        hardware_accessed=False,new_motor_trials=0,training_performed=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False,
        exporter_source_sha256=sha(__file__))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','train_boots','validation_boots')}))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();export(a.replay,a.output)
