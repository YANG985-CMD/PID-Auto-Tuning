"""Archive fixed-reference hardware evidence and frozen TD3 audits locally."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from speedloop_fixedref_probe import IDENTITY,IMAGE_SHA
from speedloop_stream_training import CausalStream,LOWER8_GAINS


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def lines(p):return [json.loads(l) for l in Path(p).read_text(encoding='utf-8').splitlines()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(source,criticAudit,output):
    src,audit,out=map(lambda p:Path(p).resolve(),(source,criticAudit,output))
    if Path('E:/dianji/motor-td3-local-results').resolve() not in out.parents or out.exists():raise ValueError('New formal archive required')
    evidence=[];keys=set();mapping={};boot_ids=[]
    for index in (0,1):
        folder=src/f'round{index}';s=read(folder/'trial/summary.json');f=read(folder/'final-readonly/summary.json')
        if (not s['passed'] or not f['passed'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
            or s['actor_applied'] or s['final_irq_fault'] or s['final_tx_fault'] or not s['protocol_stop_acknowledged']
            or not s['core_halted_after_physical_shutdown'] or not s['can_released_after_shutdown']
            or f['full_readback_sha256']!=IMAGE_SHA):raise ValueError('Physical image/shutdown verification missing')
        raw=lines(folder/'trial/telemetry.jsonl');cmds=lines(folder/'trial/commands.jsonl');events=lines(folder/'stream/events.jsonl')
        if (any(r['fault'] or r['speed_ref']!=1000 for r in raw) or len({r['boot_id'] for r in raw})!=1
            or [e['packet'] for e in events if e['kind']=='telemetry']!=raw
            or [e['command'] for e in events if e['kind']=='command']!=cmds):raise ValueError('Raw trace/event mismatch')
        boot=raw[0]['boot_id'];boot_ids.append(boot);stream=CausalStream(LOWER8_GAINS);rows=[]
        for e in events:
            if e['kind']=='command':stream.command(e['command'],e['source'])
            else:
                r=stream.telemetry(e['packet'],e['stage_proof'])
                if r:rows.append(r)
        for number,r in enumerate(rows,1):
            file=folder/f'stream/window-{number:05d}.json';key=(boot,r['first_command_seq'],r['response'][-1]['seq'])
            if read(file)!=r or key in keys:raise ValueError('Changed/repeated causal window')
            keys.add(key);mapping[str(file)]=dict(archived_path=str(out/f'round{index}'/'stream'/file.name),sha256=sha(file))
        analysis=read(folder/'gain-effect/fixedref-summary.json')
        if (analysis['actual_source_to_action_counts']!=[[5]*3]*3
            or analysis['telemetry_sha256']!=sha(folder/'trial/telemetry.jsonl')
            or analysis['commands_sha256']!=sha(folder/'trial/commands.jsonl')):raise ValueError('Matched-response input mismatch')
        duration=(s['trial_timing']['last_us']-s['trial_timing']['started_us'])/1e6
        if not 0<duration<=24:raise ValueError('Exceeded round budget')
        evidence.append(dict(boot_id=boot,split=s['predeclared_split'],windows=len(rows),
            motion_seconds=duration,actual_gain_acknowledgements=s['actual_gain_commands'],
            complete_telemetry=s['complete_telemetry_packets'],all_faults_zero=True,stop_acknowledged=True,
            six_outputs_off=True,core_halted=True,can_released=True,scores=analysis['scores']))
    if len(set(boot_ids))!=2 or sum(r['motion_seconds'] for r in evidence)>48:raise ValueError('Duplicate boot/batch duration')
    studies=('masked-actor','current-kp-actor');candidates=steps=0
    for name in studies:
        s=read(src/name/'training-summary.json')
        if (s['train_boots']!=boot_ids[0] or s['validation_boots']!=boot_ids[1]
            or s['train_windows']!=evidence[0]['windows'] or s['validation_windows']!=evidence[1]['windows']
            or s['deployment_allowed'] or s['performance_claim_allowed']):raise ValueError('Train/validation split changed')
        for r in s['input_manifest']:
            if sha(r['file'])!=r['sha256']:raise ValueError('Training input changed')
        for c in s['candidates']:
            if sha(src/name/f"candidate-{c['reward_profile']}-seed-{c['seed']}.mat")!=c['checkpoint_sha256']:
                raise ValueError('Native checkpoint changed')
        candidates+=len(s['candidates']);steps+=s['total_native_steps']
    screen=read(src/'candidate-screen.json')
    if len(screen)!=6 or any(r['projected_level_counts']['-0.5']!=143 or r['max_host_matlab_action_error']>1e-6 for r in screen):
        raise ValueError('Changed numerical/admission screen')
    report=dict(source='fixed-reference-real-motor-action-coverage-cohort',physical_evidence=evidence,
        total_real_windows=len(keys),training_windows=evidence[0]['windows'],validation_windows=evidence[1]['windows'],
        motion_seconds=sum(r['motion_seconds'] for r in evidence),maximum_batch_motion_seconds=48,
        fixedref_TD3_steps=steps,fixedref_candidates=candidates,prior_critic_ablation_steps=3600,
        prior_critic_ablation_candidates=9,fixed_ki=.00144,raw_reconstructed_and_hashes_checked=True,
        actor_applied=False,physical_Actor_validation_performed=False,temperature_gate_modified=False,
        deployment_allowed=False,performance_claim_allowed=False,github_updated=False)
    out.mkdir(parents=True)
    for index in (0,1):
        for name in ('trial','prepare','stream','final-readonly','gain-effect'):
            shutil.copytree(src/f'round{index}'/name,out/f'round{index}'/name)
    for name in studies:shutil.copytree(src/name,out/name)
    for name in ('time-validation',):shutil.copytree(src/name,out/name)
    for name in ('batch-contract.json','round0-contract.json','round1-contract.json','action-support.json',
                 'candidate-screen.json','critic-action-ranking.json'):
        shutil.copy2(src/name,out/name)
    shutil.copy2(src/'build/summary.json',out/'firmware-build-summary.json')
    shutil.copy2(src/'adapter-tests/summary.json',out/'adapter-test-summary.json')
    shutil.copy2(src/'flash/summary.json',out/'flash-summary.json')
    prior=out/'prior-critic-ablation';prior.mkdir()
    for name in ('masked-uniform','unmasked-prioritized','masked-prioritized'):shutil.copytree(audit/name,prior/name)
    for name in ('study-contract.json','candidate-screen.json','critic-input-audit.json','action-support.json','mask-tests.json'):
        shutil.copy2(audit/name,prior/name)
    (out/'workflow-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (out/'input-path-map.json').write_text(json.dumps(mapping,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='physical_evidence'}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','critic-audit','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.critic_audit,a.output)
