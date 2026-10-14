"""Analyze stopped frozen startup trace; no smoothing of protection feedback."""
import argparse,hashlib,json,math,statistics
from pathlib import Path

def run(trial,output):
    root=Path(trial).resolve();out=Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use temp root')
    s=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    d=json.loads((root/'startup-trace.json').read_text(encoding='utf-8'))
    assert d['read_only'] and d['core_halted'] and d['phase_outputs_closed'] and not any(d['overflow'].values())
    state=d['records']['state'];hall=d['records']['hall'];assert state and hall
    origin=s['trial_timing']['started_us']
    assert all(v['valid'] for v in hall)
    assert all(b['t_us']>a['t_us'] for a,b in zip(hall,hall[1:]))
    for a,b in zip(hall,hall[1:]):
        assert b['period_us']==b['t_us']-a['t_us']
        assert abs(abs(b['rpm'])-5000000/b['period_us'])<.001
    closed=next(i for i,v in enumerate(state) if v['model_stage']==4)
    assert closed>0
    before=state[closed-1];first=state[closed];peak=max(hall,key=lambda v:abs(v['rpm']))
    jump=math.atan2(math.sin(first['hall_theta']-first['open_theta']),math.cos(first['hall_theta']-first['open_theta']))
    clockratio=[e['raw_timer_ticks']/3.2/e['period_us'] for e in hall if e['period_us']>0]
    r=dict(schema_version=1,source='real_motor_frozen_startup',firmware_id=s['firmware_id'],
        bin_sha256=s['bin_sha256'],trace_sha256=hashlib.sha256((root/'startup-trace.json').read_bytes()).hexdigest(),
        total_faults=s['final_irq_fault']+s['final_tx_fault'],first_run_ms=(first['t_us']-origin)/1000,
        pre_handover_speed_rpm=before['speed_rpm'],first_run_speed_rpm=first['speed_rpm'],
        hall_peak_rpm=peak['rpm'],hall_peak_elapsed_ms=(peak['t_us']-origin)/1000,
        hall_peak_period_us=peak['period_us'],hall_peak_raw_timer_us=peak['raw_timer_ticks']/3.2,
        angle_source_difference_electrical_deg=jump*180/math.pi,
        initial_iq_command=first['iq_reference'],previous_iq_command=before['iq_reference'],
        initial_integral=first['pi_integral'],previous_integral=before['pi_integral'],
        startup_current_reference_range=[min(v['iq_reference'] for v in state),max(v['iq_reference'] for v in state)],
        timer_vs_software_period_ratio_median=statistics.median(clockratio),
        ordinary_deployment_allowed=False,performance_claim_allowed=False,
        interpretation='Hall timer independently supports shortened periods; no encoder ground truth. Angle mismatch and PI reset captured, not causal isolation.')
    out.mkdir(parents=True,exist_ok=True)
    (out/'startup-analysis.json').write_text(json.dumps(r,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(r));return r

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trial',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.trial,a.output)
