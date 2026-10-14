"""Audit two complete boots and attach causal full-Hall rewards to real windows.

Old windows/rewards remain unchanged. New action coordinates are explicitly
versioned; no old replay is appended, no hardware is opened, no policy applied.
"""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from speedloop_response_windows import temporal_mean
from speedloop_stream_training import KI
from speedloop_stream_training import UPPER8_DENSE_GAINS
from speedloop_motion_gain_trial import f32
from speedloop_fullhall_probe import IMAGE_SHA,IDENTITY


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


PROFILES={
    'lower16-fullhall':dict(version='absolute-target-lower16-scale0p00054224-v1',
        levels=tuple(map(f32,(.002856927,.003121269,.003389)))),
    'lower16-upper4-fullhall':dict(version='absolute-target-lower16-upper4-scale0p00054224-v2',
        levels=tuple(map(f32,(.002856927,.003121269,.003389,.00352456)))),
    'switching-local4-fullhall':dict(version='absolute-target-switching-local4-scale0p00054224-v3',
        levels=tuple(map(f32,(.00325344,.003389,.00352456)))),
    'upper8-fullhall':dict(version='absolute-target-upper8-scale0p00054224-v4',
        levels=tuple(map(f32,(.003389,.00352456,.00366012))),
        firmware_id='g431-speedloop-pi-upper8-24s-v24',
        firmware_sha256='42d39dcc54bae0f088a1ec0653ffdb7e9c04bae82342a4f7dd85191666d71f4f'),
    'upper8-dense-fullhall':dict(version='absolute-target-upper8-dense-scale0p00054224-v5',
        levels=UPPER8_DENSE_GAINS,
        firmwares=(('g431-speedloop-pi-upper8-24s-v24','42d39dcc54bae0f088a1ec0653ffdb7e9c04bae82342a4f7dd85191666d71f4f'),
                   ('g431-speedloop-pi-upper8-cont-24s-v25','389a05e12240e37a24a58403df691adb3f20baa499756214a3c0af6f05a98cdf')))}


def build(folders,output,splits=None,profile='lower16-fullhall'):
    if profile not in PROFILES:raise ValueError('Unreviewed full-Hall action mapping')
    mapping=PROFILES[profile]
    if splits is None:splits=['train','validation']
    if (len(folders)!=len(splits) or set(splits)!={'train','validation'}
        or any(s not in ('train','validation') for s in splits)):
        raise ValueError('Every raw physical boot needs an explicit whole-boot split')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest=[];boots=[];keys=set();counts={'train':0,'validation':0};minimum_spans=[];boot_splits=[]
    action_counts={'train':{},'validation':{}}
    for boot_index,(folder,split) in enumerate(zip(map(Path,folders),splits)):
        summary=read(folder/'trial/summary.json');ending=read(folder/'stream/session-ended.json')
        audit=read(folder/'full-hall-audit/summary.json');full=read(folder/'full-hall-audit/full-hall-edges.json')
        identities=mapping.get('firmwares',((mapping.get('firmware_id',IDENTITY),mapping.get('firmware_sha256',IMAGE_SHA)),))
        if (not summary['passed'] or (summary['firmware_id'],summary['bin_sha256']) not in identities
            or summary['actor_applied'] or summary['final_irq_fault'] or summary['final_tx_fault']
            or not all(ending[k] for k in ('physical_trial_passed','stop_acknowledged','core_halted','can_released'))
            or not audit['passed'] or not full['full_session_history'] or full['boot_id'] in boots
            or sha(folder/'stream/events.jsonl')!=audit['hashes']['events.jsonl']):
            raise ValueError('Only complete independent stopped physical sessions may enter learning')
        boots.append(full['boot_id']);edges=[r for r in full['records'] if r['model_stage']==4]
        boot_splits.append(dict(boot_id=full['boot_id'],split=split,raw_folder=str(folder.resolve())))
        times=[r['t_us'] for r in edges];count=0
        for path in sorted((folder/'stream').glob('window-*.json')):
            r=read(path);s=r['state'];z=r['response'];commands=r['commands']
            if (r['boot_id']!=full['boot_id'] or r['actor_applied'] or r['action_applied'][1]!=KI
                or r['action_applied'][0] not in mapping['levels']
                or not all(p['enabled'] and not p['fault'] and p['speed_ref']==1000 and p['ki']==KI for p in z)
                or any(p['kp']!=r['action_applied'][0] for p in z)):
                raise ValueError('Fault, unmeasured action or mixed response')
            key=f"{r['boot_id']}:{r['first_command_seq']}:{z[-1]['seq']}"
            if key in keys:raise ValueError('Duplicate physical experience')
            keys.add(key)
            lo,hi=z[0]['t_us'],z[-1]['t_us'];begin=bisect.bisect_right(times,lo)-1;end=bisect.bisect_left(times,hi)
            if begin<0 or end>=len(edges):raise ValueError('Incomplete Hall coverage of learning reward')
            slice=edges[begin:end+1];duration=0;error2=0.;peak=0.
            for a,b in zip(slice,slice[1:]):
                if (b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us']
                    or not a['valid'] or a['model_stage']!=4):raise ValueError('Hall gap in reward')
                width=max(0,min(hi,b['t_us'])-max(lo,a['t_us']))
                duration+=width;error2+=(a['rpm']-1000)**2*width
                if width:peak=max(peak,abs(a['rpm']))
            if duration!=hi-lo:raise ValueError('Reward interval is not fully covered')
            mse=error2/duration;current=max(p['current'] for p in z)
            sat=temporal_mean([float(p['current']>=1.98) for p in z],[p['t_us'] for p in z])
            legacy_mse=temporal_mean([(p['speed_ref']-p['speed'])**2 for p in z],[p['t_us'] for p in z])
            sparse_peak=max(abs(p['speed']) for p in z);delta=r['physical_delta_action'][0]
            rate=-mse/1e6-.3*(current/2)**2-.25*max(0,(peak-1500)/300)**2-.25*sat
            legacy_rate=-legacy_mse/1e6-.3*(current/2)**2-.25*max(0,(sparse_peak-1500)/300)**2-.25*sat
            dt=hi-s['t_us'];minimum_spans.append(dt)
            r.update(duration_us=dt,measured_reward_span_us=duration,
                unscored_pre_application_and_sample_latency_us=dt-duration,
                elapsed_discount=.99**(dt/100000),reference_period_us=100000,
                time_scaled_reward=rate*duration/100000-.0005*delta**2,
                legacy_time_scaled_reward=legacy_rate*duration/100000-.0005*delta**2,
                full_hall_reward=dict(begin_us=lo,end_us=hi,mse_rpm2=mse,peak_speed_rpm=peak,
                    peak_nominal_current_a=current,saturation_fraction=sat,records=slice,
                    full_hall_sha256=sha(folder/'full-hall-audit/full-hall-edges.json')),
                split=split,data_revision='complete-Hall-reward-new-action-coordinate-v1',
                action_coordinate_version=mapping['version'],
                raw_window_sha256=sha(path),physical_key=key)
            dest=output/f'{split}-boot{boot_index:02d}-{count+1:05d}.json';dest.write_text(json.dumps(r,allow_nan=False)+'\n',encoding='utf-8')
            manifest.append(dict(file=str(dest.resolve()),sha256=sha(dest),split=split,physical_key=key,
                raw_window_file=str(path.resolve()),raw_window_sha256=sha(path)))
            count+=1
            key=str(r['action_applied'][0]);action_counts[split][key]=action_counts[split].get(key,0)+1
        counts[split]+=count
    if min(counts.values())<128:raise ValueError('Less than 128 unique windows in a whole-boot split')
    report=dict(passed=True,total_unique_windows=len(manifest),unique_boots=boots,counts=counts,
        input_manifest=manifest,whole_boot_split=boot_splits,actual_action_counts=action_counts,
        unique_raw_source_boots=len(boots),old_replay_appended=False,legacy_rewards_retained=True,
        action_coordinate_version=mapping['version'],stream_gain_profile=profile,
        exact_action_kp_levels=list(mapping['levels']),
        normalized_gain_scale_kp=.00054224,physical_single_step_limit_kp=.00027112,
        fixed_ki=KI,action_mask=[1,0],duration_us_range=[min(minimum_spans),max(minimum_spans)],
        split_frozen_before_gradients=True,independent_frozen_actor_validation=False,
        hardware_accessed=False,training_performed=False,deployment_allowed=False,performance_claim_allowed=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='input_manifest'}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--train',nargs='+',required=True)
    p.add_argument('--validation',nargs='+',required=True);p.add_argument('--output',required=True)
    p.add_argument('--profile',default='lower16-fullhall',choices=tuple(PROFILES))
    a=p.parse_args();build(a.train+a.validation,a.output,['train']*len(a.train)+['validation']*len(a.validation),a.profile)
