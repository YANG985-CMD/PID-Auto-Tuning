"""Archive three stopped v19 boots and audited train/holdout studies locally."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from statistics import mean
import math
from speedloop_stream_training import CausalStream,LOWER8_GAINS
from speedloop_lower8_response import IMAGE_SHA,IDENTITY


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def lines(path):return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines()]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(source,output):
    src,out=Path(source).resolve(),Path(output).resolve()
    if Path('E:/dianji/motor-td3-local-results').resolve() not in out.parents or out.exists():
        raise ValueError('Use a new formal local results directory')
    physical=[];mapping={};all_keys=set();boots=[]
    for index,folder in enumerate(('live','repeat1','repeat2')):
        p=src/folder;t=read(p/'trial/summary.json');final=read(p/'final-readonly/summary.json')
        ending=read(p/'stream/session-ended.json')
        if (not t['passed'] or t['firmware_id']!=IDENTITY or t['bin_sha256']!=IMAGE_SHA
                or t['actor_applied'] or t['final_irq_fault'] or t['final_tx_fault']
                or not final['passed'] or not final['core_halted'] or final['full_readback_sha256']!=IMAGE_SHA
                or not t['protocol_stop_acknowledged'] or not t['can_released_after_shutdown']
                or not all(ending[k] for k in ('physical_trial_passed','stop_acknowledged','core_halted','can_released'))):
            raise ValueError('Physical shutdown/image/fault gate failed')
        raw=lines(p/'trial/telemetry.jsonl');commands=lines(p/'trial/commands.jsonl');events=lines(p/'stream/events.jsonl')
        if ([e['packet'] for e in events if e['kind']=='telemetry']!=raw
                or [e['command'] for e in events if e['kind']=='command']!=commands
                or any(r['fault'] for r in raw) or len({r['boot_id'] for r in raw})!=1):
            raise ValueError('Raw events differ or contain reset/fault')
        boots.append(raw[0]['boot_id']);stream=CausalStream(LOWER8_GAINS);rows=[]
        for e in events:
            if e['kind']=='command':stream.command(e['command'],e['source'])
            else:
                r=stream.telemetry(e['packet'],e['stage_proof'])
                if r:rows.append(r)
        for number,row in enumerate(rows,1):
            file=p/f'stream/window-{number:05d}.json'
            if read(file)!=row:raise ValueError('Committed window differs from raw causal reconstruction')
            key=(row['boot_id'],row['first_command_seq'],row['response'][-1]['seq'])
            if key in all_keys:raise ValueError('Duplicate physical experience')
            all_keys.add(key);mapping[str(file)]=dict(archived_path=str(out/f'boot-{index}'/'stream'/file.name),sha256=sha(file))
        actual=(t['trial_timing']['last_us']-t['trial_timing']['started_us'])/1e6
        if not 0<actual<=24:raise ValueError('Motion exceeded single-round budget')
        analysis=read(p/'gain-effect/gain-effect-summary.json')
        if sha(p/'trial/telemetry.jsonl')!=analysis['telemetry_sha256'] or sha(p/'trial/commands.jsonl')!=analysis['commands_sha256']:
            raise ValueError('Analysis differs from retained raw data')
        physical.append(dict(index=index,boot_id=boots[-1],actual_motion_seconds=actual,
            windows=len(rows),gain_acknowledgements=t['actual_gain_commands'],telemetry_packets=len(raw),
            split='train' if index<2 else 'validation',all_faults_zero=True,stop_acknowledged=True,
            core_halted=True,outputs_off=True,can_released=True,
            descriptive_scores=analysis['context_standardized_metrics']['scores']))
    if len(set(boots))!=3 or sum(r['actual_motion_seconds'] for r in physical[1:])>48:
        raise ValueError('Duplicate boot or cumulative repeat budget exceeded')
    studies=('fresh-sampling-study-r3','fresh-study-W25','fresh-study-W250');candidate_count=steps=0
    for name in studies:
        s=read(src/name/'training-summary.json')
        if (s['older_replay_used_for_training'] is not False or s['train_boots']!=boots[:2]
                or s['validation_boots']!=boots[2] or s['train_windows']!=sum(r['windows'] for r in physical[:2])
                or s['validation_windows']!=physical[2]['windows'] or s['deployment_allowed'] or s['performance_claim_allowed']):
            raise ValueError('Training/holdout boot split or gate changed')
        for item in s['input_manifest']:
            if sha(item['file'])!=item['sha256']:raise ValueError('Native training input changed')
        for c in s['candidates']:
            path=src/name/f"candidate-{c['reward_profile']}-seed-{c['seed']}.mat"
            if sha(path)!=c['checkpoint_sha256']:raise ValueError('Checkpoint changed')
        candidate_count+=len(s['candidates']);steps+=s['total_native_steps']
    aggregate=[]
    for level in (0,1,2):
        scores=[r['descriptive_scores'][level] for r in physical]
        aggregate.append(dict(level=level,rmse_rpm=math.sqrt(mean(s['rmse_rpm']**2 for s in scores)),
            mean_peak_nominal_current_a=mean(s['mean_peak_nominal_current_a'] for s in scores),
            mean_peak_speed_rpm=mean(s['mean_peak_speed_rpm'] for s in scores)))
    for s in aggregate:
        s['rmse_improvement_fraction']=1-s['rmse_rpm']/aggregate[0]['rmse_rpm']
    result=dict(source='post-sampling-fix-lower8-real-motor-cohort',physical_boots=physical,
        actual_motion_seconds=sum(r['actual_motion_seconds'] for r in physical),maximum_motion_seconds=72,
        total_new_windows=len(all_keys),training_windows=sum(r['windows'] for r in physical[:2]),
        validation_windows=physical[2]['windows'],fresh_native_td3_steps=steps,
        live_native_td3_steps=read(src/'live/matlab-r2/training-summary.json')['gradient_steps'],
        fresh_candidates=candidate_count,aggregate_descriptive_scores=aggregate,
        aggregate_is_not_Actor_performance=True,raw_events_reconstructed=True,window_hashes_verified=True,
        actor_applied=False,ordinary_deployment_allowed=False,performance_claim_allowed=False,
        fixed_ki=.00144,thermal_gate_modified=False,current_conversion_independently_calibrated=False,
        independent_cpu_stall_watchdog_integrated=False)
    out.mkdir(parents=True)
    for index,folder in enumerate(('live','repeat1','repeat2')):
        for name in ('trial','prepare','stream','final-readonly','gain-effect'):
            shutil.copytree(src/folder/name,out/f'boot-{index}'/name)
    shutil.copytree(src/'live/matlab-r2',out/'online-matlab')
    shutil.copytree(src/'live/diagnostics',out/'online-diagnostics')
    for name in studies:shutil.copytree(src/name,out/name)
    for name in ('numerical','cohort-time-audit'):
        shutil.copytree(src/name,out/name)
    shutil.copy2(src/'adapter-tests/summary.json',out/'adapter-test-summary.json')
    for name in ('schedule-contract.json','repeat1-contract.json','repeat2-contract.json','repeat-batch-contract.json',
                 'heldout-policy-ablation.json','actor-loss-audit.json','matlab-support-tests.json'):
        shutil.copy2(src/name,out/name)
    shutil.copy2(src/'build/summary.json',out/'firmware-build-summary.json')
    shutil.copy2(src/'flash/summary.json',out/'flash-summary.json')
    for name in ('workflow-summary','input-path-map'):
        (out/(name+'.json')).write_text(json.dumps(result if name=='workflow-summary' else mapping,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('physical_boots','aggregate_descriptive_scores')}))
    print(json.dumps(aggregate))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.source,a.output)
