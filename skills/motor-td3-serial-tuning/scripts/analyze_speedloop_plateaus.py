"""Audit predeclared actual-ACK plateau responses; no hardware or training."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from speedloop_response_windows import temporal_mean
from speedloop_stream_training import CausalStream
from speedloop_motion_handshake import PHASE_MASK

def analyze(stream,trial_summary,contract,output):
    stream,trial_summary,contract,output=map(Path,(stream,trial_summary,contract,output))
    summary=json.loads(trial_summary.read_text(encoding='utf-8'))
    cfg=json.loads(contract.read_text(encoding='utf-8'))
    interior=cfg.get('probe_mode')=='upper8-continuous-interior'
    transient=interior or cfg.get('probe_mode') in ('switching-local4','upper8-switching')
    if interior and (cfg.get('training_purpose')!='actual-source-gain-switch-response'
        or cfg.get('independent_performance_evaluation') is not False
        or cfg.get('plateau_ms')!=4500 or cfg.get('analysis_settle_ms')!=200
        or cfg.get('analysis_end_margin_ms')!=200 or len(cfg.get('pattern',[]))!=4):
        raise ValueError('Interior acquisition is a predeclared transient probe, not steady performance validation')
    if transient and not interior and (cfg.get('training_purpose')!='actual-source-gain-switch-response'
        or cfg.get('independent_performance_evaluation') is not False
        or cfg.get('plateau_ms')!=500 or cfg.get('analysis_settle_ms')!=100
        or cfg.get('analysis_end_margin_ms')!=50 or len(cfg.get('pattern',[]))!=32):
        raise ValueError('Transient response audit requires the exact predeclared switching contract')
    if hashlib.sha256(contract.read_bytes()).hexdigest()!=summary.get('schedule_contract_sha256'):
        raise ValueError('Evaluation interval changed after the physical experiment')
    if (not summary['passed'] or not summary['protocol_stop_acknowledged']
        or summary['final_irq_fault'] or summary['final_tx_fault']
        or not summary['core_halted_after_physical_shutdown'] or not summary['can_released_after_shutdown']):
        raise ValueError('Incomplete stop/fault evidence; no performance comparison')
    gates=summary['final_board_state']
    if (gates['tim1_bdtr']&0x8000 or gates['tim1_ccer']&PHASE_MASK
        or gates['gpioa_moder']&0x3f0000!=0x150000 or gates['gpiob_moder']&0xfc000000!=0x54000000
        or gates['gpioa_odr']&0x700 or gates['gpiob_odr']&0xe000):
        raise ValueError('Reported physical outputs are not inhibited')
    commands={};packets=[];boot=None;last=None;started=None
    for line in (stream/'events.jsonl').read_text(encoding='utf-8').splitlines():
        item=json.loads(line)
        if item['kind']=='command':
            c=item['command']
            if c['type']=='gains':
                if c['command_seq']!=len(commands)+1:raise ValueError('Command gap or duplicate')
                source=item['source']
                if source is None or source!=last or c['source_t_us']!=source['t_us']:
                    raise ValueError('Command source differs from latest actual state')
                commands[c['command_seq']]=c
            continue
        t=item['packet'];proof=item['stage_proof']
        if boot is None:boot=t['boot_id']
        if (boot!=t['boot_id'] or t['fault'] or last and
            (t['seq']!=last['seq']+1 or not 15000<=t['t_us']-last['t_us']<=25000)):
            raise ValueError('Mixed boot, fault or sequence/time gap')
        if not all(math.isfinite(t[k]) for k in ('speed_ref','speed','current','vbus','kp','ki')):
            raise ValueError('Nonfinite observation')
        if t['enabled'] and (abs(t['speed'])>=1800 or t['current']>=2 or not 18<=t['vbus']<=30):
            raise ValueError('Physical boundary violation')
        if t['applied_seq']:
            c=commands.get(t['applied_seq'])
            if (c is None or [c['kp'],c['ki']]!=[t['kp'],t['ki']]
                or not c['source_t_us']<=t['t_apply_us']<=c['expires_us']):
                raise ValueError('Missing actual action acknowledgement')
        if t['enabled'] and t['elapsed_ms']>=3900:
            if not CausalStream.valid_stage(proof,t):raise ValueError('Missing RunStage proof')
            if started is None:started=proof['started_us']
            if started!=proof['started_us']:raise ValueError('Changed stage origin')
        packets.append(t);last=t
    raw_packets=[json.loads(line) for line in (trial_summary.parent/'telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    if raw_packets!=packets:raise ValueError('Journal differs from retained raw telemetry')
    records=[]
    for slot,level in enumerate(cfg['pattern']):
        begin=cfg['plateau_start_ms']+slot*cfg['plateau_ms'];end=begin+cfg['plateau_ms']
        target=cfg['exact_kp_levels'][level];ki=cfg['fixed_ki']
        within=[p for p in packets if p['enabled'] and begin<=p['elapsed_ms']<end]
        if not within:raise ValueError('Missing plateau')
        matched=[p for p in within if p['kp']==target and p['ki']==ki and p['applied_seq']]
        if not matched:raise ValueError('Requested target never acknowledged')
        effective=max(begin,(matched[0]['t_apply_us']-started)/1000)
        score_begin=effective+cfg['analysis_settle_ms'];score_end=end-cfg['analysis_end_margin_ms']
        selected=[p for p in within if score_begin<=p['elapsed_ms']<score_end]
        if (len(selected)<(8 if transient else 40)
            or selected[-1]['t_us']-selected[0]['t_us']<(140000 if transient else 1000000)
            or any(p['kp']!=target or p['ki']!=ki or p['speed_ref']!=cfg['reference_rpm'] for p in selected)):
            raise ValueError('Incomplete or mixed-action response plateau')
        times=[p['t_us'] for p in selected]
        mse=temporal_mean([(p['speed_ref']-p['speed'])**2 for p in selected],times)
        records.append(dict(slot=slot,level=level,kp=target,ki=ki,planned_start_ms=begin,
            actual_target_effective_ms=effective,analysis_start_ms=score_begin,analysis_end_ms=score_end,
            packet_count=len(selected),first_seq=selected[0]['seq'],last_seq=selected[-1]['seq'],
            response_is_steady_state=not transient,
            duration_us=times[-1]-times[0],mse_rpm2=mse,rmse_rpm=math.sqrt(mse),
            peak_nominal_current_a=max(p['current'] for p in selected),
            peak_speed_rpm=max(abs(p['speed']) for p in selected),
            saturation_fraction=temporal_mean([float(p['current']>=1.98) for p in selected],times)))
    groups=defaultdict(list)
    for r in records:groups[r['level']].append(r)
    metrics={}
    for level,rows in groups.items():
        metrics[str(level)]=dict(kp=rows[0]['kp'],plateau_count=len(rows),
            rmse_rpm=math.sqrt(sum(r['mse_rpm2'] for r in rows)/len(rows)),
            mean_peak_nominal_current_a=sum(r['peak_nominal_current_a'] for r in rows)/len(rows),
            mean_peak_speed_rpm=sum(r['peak_speed_rpm'] for r in rows)/len(rows),
            saturation_fraction=sum(r['saturation_fraction'] for r in rows)/len(rows))
    base=metrics['0'];comparisons={}
    for level,m in metrics.items():
        if level=='0':continue
        improvement=100*(1-m['rmse_rpm']/base['rmse_rpm'])
        comparisons[level]=dict(rmse_improvement_percent=improvement,
            descriptive_single_boot_gate_passed=not transient and improvement>=5 and
                m['mean_peak_nominal_current_a']<=base['mean_peak_nominal_current_a'] and
                m['mean_peak_speed_rpm']<=base['mean_peak_speed_rpm'],
            independent_validation_passed=False)
    result=dict(passed=True,boot_id=boot,unique_boots=1,actual_command_count=len(commands),
        complete_packets=len(packets),plateaus=records,metrics=metrics,comparisons=comparisons,
        startup_excluded_from_score_not_from_fault_log=True,bridge_excluded_from_target_response=True,
        descriptive_only=True,actor_applied=False,training_performed=False,
        transient_response_audit=transient,independent_performance_evaluation=not transient,
        deployment_allowed=False,performance_claim_allowed=False,
        hashes={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (stream/'events.jsonl',trial_summary,contract)})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,metrics=metrics,comparisons=comparisons)));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('stream','trial-summary','contract','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();analyze(a.stream,a.trial_summary,a.contract,a.output)
