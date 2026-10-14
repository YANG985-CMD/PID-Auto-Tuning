"""Archive real Ki response evidence locally; never mark it TD3 training."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from speedloop_ki_response import IMAGE_SHA, IDENTITY, KI_LEVELS
from speedloop_motion_gain_trial import f32
from speedloop_response_windows import lines


def run(source, build, contract, output):
    source, build, contract, out = (Path(p).resolve() for p in (source, build, contract, output))
    if Path('E:/dianji/motor-td3-local-results').resolve() not in out.parents or out.exists():
        raise ValueError('Use a new formal local results directory')
    s = json.loads((source/'trial/summary.json').read_text(encoding='utf-8'))
    final = json.loads((source/'final-readonly/summary.json').read_text(encoding='utf-8'))
    analysis = json.loads((source/'gain-effect/gain-effect-summary.json').read_text(encoding='utf-8'))
    if (not s['passed'] or not final['passed'] or s['firmware_id']!=IDENTITY or s['bin_sha256']!=IMAGE_SHA
            or final['full_readback_sha256']!=IMAGE_SHA or not final['core_halted']
            or not s['protocol_stop_acknowledged'] or not s['can_released_after_shutdown']
            or s['final_irq_fault'] or s['final_tx_fault'] or final['irq_fault'] or final['tx_fault']
            or s['actor_applied'] or s['td3_training_performed'] or s['ki_data_added_to_existing_kp_only_replay']
            or hashlib.sha256(contract.read_bytes()).hexdigest()!=s['schedule_contract_sha256']):
        raise ValueError('Missing complete physical shutdown or wrong evidence claim')
    raw = lines(source/'trial/telemetry.jsonl')
    commands = lines(source/'trial/commands.jsonl')
    applied = {r['applied_seq'] for r in raw if r['enabled'] and r['applied_seq']}
    if ({c['command_seq'] for c in commands if c['type']=='gains'}!=applied
            or len(raw)!=s['complete_telemetry_packets'] or len({r['boot_id'] for r in raw})!=1
            or any(r['fault'] for r in raw)
            or any(r['kp']!=f32(.003389) or r['ki'] not in KI_LEVELS for r in raw if r['enabled'])):
        raise ValueError('Missing application or changed raw Ki evidence')
    for name,key in [('telemetry.jsonl','telemetry_sha256'),('commands.jsonl','commands_sha256')]:
        if hashlib.sha256((source/'trial'/name).read_bytes()).hexdigest()!=analysis[key]:
            raise ValueError('Analysis does not match retained raw evidence')
    duration=(s['trial_timing']['last_us']-s['trial_timing']['started_us'])/1e6
    if not 0<duration<=24:
        raise ValueError('Motion exceeded finite budget')
    out.mkdir(parents=True)
    for folder in ('trial','prepare','final-readonly','gain-effect'):
        shutil.copytree(source/folder,out/folder)
    journal_present='stage_journal' in s
    if journal_present:
        proof=json.loads((source/'stage-journal/stage-journal-summary.json').read_text(encoding='utf-8'))
        if (not proof['closed'] or proof['error'] is not None
                or hashlib.sha256((source/'stage-journal/events.jsonl').read_bytes()).hexdigest()!=proof['event_sha256']):
            raise ValueError('Invalid stage proof archive')
        shutil.copytree(source/'stage-journal',out/'stage-journal')
    shutil.copy2(contract,out/'schedule-contract.json')
    shutil.copy2(build/'summary.json',out/'firmware-build-summary.json')
    report=dict(source='actual_motor_ki_response_capture_only',hardware_test_passed=True,
        actual_motion_seconds=duration,maximum_motion_seconds=24,actual_gain_acknowledgements=len(applied),
        telemetry_packets=len(raw),fixed_kp=f32(.003389),actual_ki_levels=list(KI_LEVELS),
        all_faults_zero=True,stop_acknowledged=True,outputs_off=True,core_halted=True,can_released=True,
        nominal_peak_current_a=s['nominal_peak_current_a'],peak_speed_rpm=s['peak_speed_rpm'],
        response_metrics=analysis['context_standardized_metrics']['scores'],
        td3_training_performed=False,actor_applied=False,ki_action_mask_activated=False,
        added_to_kp_only_replay=False,per_packet_stage_journal_present=journal_present,
        temperature_gate_modified=False,current_conversion_independently_calibrated=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (out/'workflow-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','contract','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    run(args.source,args.build,args.contract,args.output)
