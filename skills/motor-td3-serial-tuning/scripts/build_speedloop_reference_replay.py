"""Actual v22/v23 local +/-4% data; reject windows spanning reference steps."""
import argparse
import bisect
import json
from pathlib import Path
from build_speedloop_fullhall_replay import read,sha
from speedloop_reference_v23 import IDENTITY,IMAGE_SHA
from speedloop_sampling_v22 import IDENTITY as OLD_ID,IMAGE_SHA as OLD_SHA
from speedloop_fullhall_probe import SWITCH_LEVELS
from speedloop_stream_training import KI
from speedloop_response_windows import temporal_mean

VERSION='absolute-target-switching-local4-scale0p00054224-v3'
REVISION='reference-excited-local4-capture-v1'


def reference_for_window(window,permitted):
    refs={p['speed_ref'] for p in [*window['state_history'],*window['response']]}
    if not refs<=permitted:raise ValueError('Unknown actual reference')
    return refs.pop() if len(refs)==1 else None


def build(folders,splits,output):
    return build_profile(folders,splits,output,dynamic_identity=IDENTITY,dynamic_sha=IMAGE_SHA,
        fixed_identity=OLD_ID,fixed_sha=OLD_SHA,dynamic_profile='exogenous-v23-950-1000-1050',
        gains=SWITCH_LEVELS,version=VERSION,revision=REVISION,stream_profile='switching-local4-fullhall')


def build_profile(folders,splits,output,*,dynamic_identity,dynamic_sha,fixed_identity,fixed_sha,
                  dynamic_profile,gains,version,revision,stream_profile,fixed_extra=(),
                  dynamic_extra=(),host_step_limit=None):
    if len(folders)!=len(splits) or set(splits)!={'train','validation'}:raise ValueError('Explicit whole-boot split required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifests=[];boots=[];keys=set();rejected=[];boot_splits=[];counts={'train':0,'validation':0}
    for boot_index,(raw,split) in enumerate(zip(folders,splits)):
        folder=Path(raw);summary=read(folder/'trial/summary.json');ending=read(folder/'stream/session-ended.json')
        audit=read(folder/'full-hall-audit/summary.json');full=read(folder/'full-hall-audit/full-hall-edges.json')
        pair=(summary['firmware_id'],summary['bin_sha256'])
        dynamic_profiles={(dynamic_identity,dynamic_sha):dynamic_profile,
            **{(identity,digest):profile for identity,digest,profile in dynamic_extra}}
        known=pair in (*dynamic_profiles,(fixed_identity,fixed_sha),*fixed_extra)
        if (not known or not summary['passed'] or summary['actor_applied'] or summary['final_irq_fault'] or summary['final_tx_fault']
            or not all(ending[k] for k in ('physical_trial_passed','stop_acknowledged','core_halted','can_released'))
            or not audit['passed'] or not full['full_session_history'] or full['boot_id'] in boots
            or sha(folder/'stream/events.jsonl')!=audit['hashes']['events.jsonl']):
            raise ValueError('Need exact known, distinct, complete safely stopped sessions')
        if pair in dynamic_profiles and summary.get('reference_profile')!=dynamic_profiles[pair]:
            raise ValueError('Missing actual reference generation contract')
        boots.append(full['boot_id']);boot_splits.append(dict(boot_id=full['boot_id'],split=split,
            raw_folder=str(folder.resolve()),firmware_id=pair[0],firmware_sha256=pair[1]))
        edges=[r for r in full['records'] if r['model_stage']==4];times=[e['t_us'] for e in edges]
        for path in sorted((folder/'stream').glob('window-*.json')):
            r=read(path);s=r['state'];z=r['response'];key=f"{r['boot_id']}:{r['first_command_seq']}:{z[-1]['seq']}"
            if key in keys:raise ValueError('Duplicate physical window')
            keys.add(key)
            permitted={950.,1000.,1050.} if pair in dynamic_profiles else {1000.}
            ref=reference_for_window(r,permitted)
            if (r['boot_id']!=full['boot_id'] or r['actor_applied'] or r['action_applied'][1]!=KI
                or r['action_applied'][0] not in gains or s['kp'] not in gains
                or any(not p['enabled'] or p['fault'] or p['kp']!=r['action_applied'][0] or p['ki']!=KI for p in z)):
                raise ValueError('Unmeasured or mixed actual gain/response')
            if host_step_limit is not None and abs(r['action_applied'][0]-s['kp'])>host_step_limit+1e-9:
                rejected.append(dict(physical_key=key,raw_window_file=str(path.resolve()),raw_window_sha256=sha(path),
                    reason='Actual historical step exceeds the current host execution limit; not clipped'));continue
            if ref is None:
                rejected.append(dict(physical_key=key,raw_window_file=str(path.resolve()),raw_window_sha256=sha(path),
                    reason='Source/history/response spans an exogenous reference change'));continue
            lo,hi=z[0]['t_us'],z[-1]['t_us'];begin=bisect.bisect_right(times,lo)-1;end=bisect.bisect_left(times,hi)
            if begin<0 or end>=len(edges):raise ValueError('Incomplete Hall reward span')
            trace=edges[begin:end+1];duration=mse=0.;peak=0.
            for a,b in zip(trace,trace[1:]):
                if not a['valid'] or b['edge']!=a['edge']+1 or b['t_us']-a['t_us']!=b['period_us']:raise ValueError('Hall gap')
                width=max(0,min(hi,b['t_us'])-max(lo,a['t_us']));duration+=width;mse+=width*(a['rpm']-ref)**2
                if width:peak=max(peak,abs(a['rpm']))
            if duration!=hi-lo:raise ValueError('Incomplete covered reward')
            mse/=duration;current=max(p['current'] for p in z);delta=r['physical_delta_action'][0]
            sat=temporal_mean([float(p['current']>=1.98) for p in z],[p['t_us'] for p in z])
            old_mse=temporal_mean([(p['speed_ref']-p['speed'])**2 for p in z],[p['t_us'] for p in z])
            old_peak=max(abs(p['speed']) for p in z)
            rate=-mse/1e6-.3*(current/2)**2-.25*max(0,(peak-1500)/300)**2-.25*sat
            old_rate=-old_mse/1e6-.3*(current/2)**2-.25*max(0,(old_peak-1500)/300)**2-.25*sat
            dt=hi-s['t_us']
            r.update(duration_us=dt,measured_reward_span_us=duration,
                unscored_pre_application_and_sample_latency_us=dt-duration,
                elapsed_discount=.99**(dt/100000),reference_period_us=100000,
                time_scaled_reward=rate*duration/100000-.0005*delta**2,
                legacy_time_scaled_reward=old_rate*duration/100000-.0005*delta**2,
                full_hall_reward=dict(begin_us=lo,end_us=hi,mse_rpm2=mse,peak_speed_rpm=peak,
                    peak_nominal_current_a=current,saturation_fraction=sat,records=trace,
                    reference_rpm=ref,full_hall_sha256=sha(folder/'full-hall-audit/full-hall-edges.json')),
                split=split,data_revision='complete-Hall-reward-new-action-coordinate-v1',
                reference_data_revision=revision,action_coordinate_version=version,
                raw_window_sha256=sha(path),physical_key=key)
            dest=output/f'{split}-boot{boot_index:02d}-{counts[split]+1:05d}.json'
            dest.write_text(json.dumps(r)+'\n');counts[split]+=1
            manifests.append(dict(file=str(dest.resolve()),sha256=sha(dest),split=split,physical_key=key,
                raw_window_file=str(path.resolve()),raw_window_sha256=sha(path)))
    if min(counts.values())<128:raise ValueError('Need 128 distinct windows per whole-boot split')
    report=dict(passed=True,total_unique_windows=len(manifests),counts=counts,unique_boots=boots,whole_boot_split=boot_splits,
        input_manifest=manifests,rejected_windows=rejected,old_replay_appended=False,
        raw_sources_rebuilt_once=True,legacy_rewards_retained=True,reference_data_revision=revision,
        action_coordinate_version=version,stream_gain_profile=stream_profile,
        exact_action_kp_levels=sorted(gains),normalized_gain_scale_kp=.00054224,
        physical_single_step_limit_kp=.00027112,fixed_ki=KI,action_mask=[1,0],
        references_allowed_rpm=[950,1000,1050],reference_crossing_windows_rejected=True,
        split_frozen_before_gradients=True,hardware_accessed=False,training_performed=False,
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('input_manifest','rejected_windows','whole_boot_split')}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train',nargs='+',required=True);p.add_argument('--validation',nargs='+',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();build(a.train+a.validation,['train']*len(a.train)+['validation']*len(a.validation),a.output)
