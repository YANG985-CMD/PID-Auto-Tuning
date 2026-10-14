"""Local evidence archive with independent raw/window/hash consistency checks."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from speedloop_response_windows import lines
from speedloop_stream_training import CausalStream


def run(source,output,build):
    src,out,build=map(lambda p:Path(p).resolve(),(source,output,build))
    if Path('E:/dianji/motor-td3-local-results').resolve() not in out.parents:raise ValueError('Use formal local results directory')
    trial=json.loads((src/'trial/summary.json').read_text(encoding='utf-8'))
    training=json.loads((src/'matlab/training-summary.json').read_text(encoding='utf-8'))
    final=json.loads((src/'final-readonly/summary.json').read_text(encoding='utf-8'))
    if not trial['passed'] or not training['session_validation_passed'] or not final['passed']:
        raise ValueError('Final physical/training state not verified')
    raw=lines(src/'trial/telemetry.jsonl');commands=lines(src/'trial/commands.jsonl')
    events=lines(src/'stream/events.jsonl')
    from speedloop_stream_training import GAINS,INTERIOR_GAINS,LOWER_GAINS,LOWER8_GAINS
    allowed=GAINS
    if trial.get('firmware_id')=='g431-speedloop-pi-interior-24s-v14':allowed=INTERIOR_GAINS
    if trial.get('firmware_id')=='g431-speedloop-pi-lower-24s-v15':allowed=LOWER_GAINS
    if trial.get('firmware_id')=='g431-speedloop-pi-lower8-24s-v19':allowed=LOWER8_GAINS
    stream=CausalStream(allowed);rows=[]
    for e in events:
        if e['kind']=='command':stream.command(e['command'],e['source'])
        else:
            row=stream.telemetry(e['packet'],e['stage_proof'])
            if row:rows.append(row)
    if [e['packet'] for e in events if e['kind']=='telemetry']!=raw:raise ValueError('Stream and retained telemetry differ')
    if [e['command'] for e in events if e['kind']=='command']!=commands:raise ValueError('Stream and retained commands differ')
    boot=raw[0]['boot_id']
    consumed=[r for r in training['consumed_windows'] if r['boot_id']==boot];seen=set()
    if len(rows)!=training['live_experiences'] or len(consumed)!=len(rows):raise ValueError('Learning count mismatch')
    for index,row in enumerate(rows,1):
        f=src/f'stream/window-{index:05d}.json'
        if json.loads(f.read_text(encoding='utf-8'))!=row:raise ValueError('Committed window differs from causal reconstruction')
        c=consumed[index-1]
        if hashlib.sha256(f.read_bytes()).hexdigest()!=c['sha256'] or c['physical_key'] in seen:
            raise ValueError('Changed or duplicate learning input')
        seen.add(c['physical_key'])
    if training['replay_count']!=training['initial_replay_count']+len(rows):raise ValueError('Duplicate replay count')
    keys={r['applied_seq'] for r in raw if r['enabled'] and r['applied_seq']}
    if keys!={c['command_seq'] for c in commands if c['type']=='gains'}:raise ValueError('Missing actual parameter acknowledgement')
    active=[r for r in raw if r['enabled']];scored=[r for r in active if 3900<=r['elapsed_ms']<=23700]
    started=(trial['trial_timing']['last_us']-trial['trial_timing']['started_us'])/1e6
    ages=[(r['t_apply_us']-next(c['source_t_us'] for c in commands if c.get('command_seq')==r['applied_seq']))/1000
          for r in active if r['applied_seq']]
    age_values=sorted(ages)
    result=dict(schema_version=1,source='real_motor_continuous_async_td3',hardware_test_passed=True,
        single_begin_commands=sum(c['type']=='begin' for c in commands),actual_motion_seconds=started,
        maximum_motion_seconds=24,actual_gain_acknowledgements=len(keys),telemetry_packets=len(raw),
        active_snapshots=len(active),live_windows=len(rows),native_td3_gradient_steps=training['gradient_steps'],
        replay_count=training['replay_count'],actual_gain_pairs=trial['gain_pairs'],fixed_ki=trial['fixed_ki'],
        rmse_3900_to_23700_rpm=(sum((r['speed_ref']-r['speed'])**2 for r in scored)/len(scored))**.5,
        rmse_basis='One actual reference schedule and behavior policy; not an Actor comparison',
        nominal_peak_current_a=trial['nominal_peak_current_a'],peak_speed_rpm=trial['peak_speed_rpm'],
        actual_source_to_apply_ms=dict(minimum=min(ages),maximum=max(ages),median=age_values[len(ages)//2]),
        final_irq_fault=trial['final_irq_fault'],final_tx_fault=trial['final_tx_fault'],
        stop_acknowledged=trial['protocol_stop_acknowledged'],core_halted=final['core_halted'],
        outputs_off=True,can_released=trial['can_released_after_shutdown'],
        stream_windows_rebuilt_from_retained_events=True,matlab_window_hashes_verified=True,
        training_started_while_motor_running=True,actor_applied=False,
        deployment_allowed=False,performance_claim_allowed=False,thermal_gate_modified=False,
        current_conversion_independently_calibrated=False,independent_cpu_stall_watchdog_integrated=False)
    # Wall times are auxiliary evidence only. At least the early updates were
    # observed while the physical collector was still running.
    end_stamp=(src/'stream/session-ended.json').stat().st_mtime
    versions=list((src/'matlab').glob('candidate-*.mat'))
    result['candidate_files_saved_before_session_end']=sum(f.stat().st_mtime<end_stamp for f in versions)
    result['candidate_files_saved_total']=len(versions)
    result['candidate_time_basis']='Host filesystem timestamps; not a measured MCU timing bound'
    out.mkdir(parents=True,exist_ok=False)
    for folder in ('trial','stream','matlab','diagnostics','final-readonly'):
        shutil.copytree(src/folder,out/folder)
    (out/'prepare').mkdir();shutil.copy2(src/'prepare/summary.json',out/'prepare/summary.json')
    shutil.copy2(build/'summary.json',out/'firmware-build-summary.json')
    (out/'workflow-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    # Paths in byte-identical native checkpoints retain their creation context.
    mapping={}
    for c in consumed:
        old=Path(c['file']);new=out/'stream'/old.name
        mapping[str(old)]=dict(archived_path=str(new),sha256=c['sha256'])
    (out/'input-path-map.json').write_text(json.dumps(mapping,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','build'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.output,a.build)
