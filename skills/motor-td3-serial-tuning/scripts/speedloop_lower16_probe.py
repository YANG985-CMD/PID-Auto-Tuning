"""One predeclared 24s fixed-reference probe, actual-readback staged Kp changes.

Capture only. New actions are not compatible with the old TD3 action mapping.
Fault ends this experiment; no automatic retry. No thermal gate modification.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import speedloop_continuous as continuous
from speedloop_duration_review import overrides
from speedloop_fixedref_probe import IMAGE_SHA as OLD_SHA,IMAGE_BYTES as OLD_BYTES
from speedloop_motion_gain_trial import f32
from speedloop_stream_training import LOWER16_GAINS
from build_speedloop_lower16_review import IDENTITY

IMAGE_SHA='8ffff6c37ee50ac9249c27b847816caf5768a8137b4580f4ce47684e56dabd1a'
HEX_SHA='cf5f12ef8b7aa5ae77e5870b938a9ec82850ae79a7572647b92b5adc5600d11a'
IMAGE_BYTES=51136
LEVELS=tuple(map(f32,(.003389,.003121269,.002856927)))
PATTERN=(0,2,2,0,0,2,2,0)
KI=f32(.00144)
STEP=f32(.00027112)
PLATEAU_START_MS=6000
PLATEAU_MS=2000
PLATEAU_END_MS=22000
ANALYSIS_SETTLE_MS=200
ANALYSIS_END_MARGIN_MS=200
REFERENCE_MATCHES=lambda ms,ref:ref==1000

class StagedProbe:
    def __init__(self):self.slot=-1;self.actual=LEVELS[0];self.decisions=[]
    def observe(self,t):
        # Original fuzzy initialization reports its own gains before BEGIN.
        # They are logged by BASE_CHECK/journal, never treated as applied probes.
        if not t.get('enabled',True) or not t.get('applied_seq',1):return
        if t['kp'] not in LOWER16_GAINS or t['ki']!=KI:raise RuntimeError('Unknown actual gains')
        self.actual=t['kp']
    def planned(self,elapsed,ki_probe_sign=0,mode='kp_probe'):
        if ki_probe_sign or mode!='kp_probe':raise ValueError('Fixed Ki, no Actor')
        slot=int((elapsed-PLATEAU_START_MS)//PLATEAU_MS) if PLATEAU_START_MS<=elapsed<PLATEAU_END_MS else -1
        if slot>=0 and (slot<self.slot or self.slot>=0 and slot>self.slot+1):
            raise RuntimeError('Missed plateau; stop instead of skipping experiment')
        target=LEVELS[PATTERN[slot]] if slot>=0 else LEVELS[0]
        if slot>=0:self.slot=slot
        command=target if abs(target-self.actual)<=STEP+1e-9 else LEVELS[1]
        if abs(command-self.actual)>STEP+1e-9:raise RuntimeError('Cannot bridge actual gain within old slew limit')
        self.decisions.append(dict(source_elapsed_ms=elapsed,slot=slot,actual_kp=self.actual,
            target_kp=target,command_kp=command,intermediate_bridge=command!=target))
        return command,KI

def validate_prior_trial(a,old):
    if (not old['passed'] or old['final_irq_fault'] or old['final_tx_fault']
        or not old['protocol_stop_acknowledged'] or not old['can_released_after_shutdown']
        or not old['core_halted_after_physical_shutdown']):raise ValueError('Prior fault ends batch')


def validate(a):
    if not getattr(a,'authorized_larger_exploration',False):raise ValueError('Direct human exploration authorization required')
    a.authorized_continuous=True
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES):
        info=continuous.validate(a)
    r=info.get('lower16_review',{})
    if (r.get('exact_kp_levels')!=[.003389,.003121269,.002856927] or r.get('fixed_ki')!=.00144
        or r.get('required_bridge_kp')!=.003121269 or r.get('maximum_single_command_kp_change')!=.00027112
        or r.get('current_speed_bus_duration_lease_limits_modified') is not False
        or r.get('thermal_gate_modified') is not False or r.get('actor_allowed') is not False):
        raise ValueError('Changed physical experiment contract')
    if a.phase!='flash':
        c=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
        if (c.get('requested_rounds')!=1 or c.get('reserved_motion_seconds')!=24
            or c.get('pattern')!=list(PATTERN) or c.get('plateau_start_ms')!=PLATEAU_START_MS or c.get('plateau_ms')!=PLATEAU_MS
            or c.get('exact_kp_levels')!=list(LEVELS) or c.get('fixed_ki')!=KI
            or c.get('reference_rpm')!=1000 or c.get('actor_applied') is not False
            or c.get('fault_automatic_retry') is not False or c.get('training_performed') is not False
            or c.get('analysis_settle_ms')!=ANALYSIS_SETTLE_MS or c.get('analysis_end_margin_ms')!=ANALYSIS_END_MARGIN_MS):
            raise ValueError('Finite schedule must be declared before motion')
        old=json.loads(Path(a.previous_trial_summary).read_text(encoding='utf-8'))
        validate_prior_trial(a,old)
        # The old UTC stamp is at entry. Subtract its full capture cap, not its average run time.
        cooldown=(datetime.now(timezone.utc)-datetime.fromisoformat(old['utc'])).total_seconds()-26
        if cooldown<30:raise ValueError('Verified cooldown below 30 seconds')
    if a.phase=='trial' and Path(a.output).exists():raise ValueError('Consumed experiment cannot be repeated')
    return info

def run(a):
    validate(a);a.stream_gain_levels=LOWER16_GAINS;a.capture_only=True;a.trainer_ready_file=None
    with overrides(continuous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,HEX_SHA=HEX_SHA,IMAGE_BYTES=IMAGE_BYTES,
        OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES,ContinuousProbe=StagedProbe,reference_matches=REFERENCE_MATCHES):
        result=continuous.run(a)
    if a.phase=='trial':
        result.update(probe_pattern=list(PATTERN),plateau_start_ms=PLATEAU_START_MS,plateau_ms=PLATEAU_MS,
            exact_kp_levels=list(LEVELS),fixed_ki=KI,fixed_reference_rpm=1000,
            behavior_policy='actual-readback-staged-long-plateaus-v1',capture_only=True,
            online_training_performed=False,action_mapping_redefinition_required=True,
            schedule_contract_sha256=hashlib.sha256(Path(a.schedule_contract).read_bytes()).hexdigest())
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('flash','prepare','trial'))
    for n in ('build','output'):p.add_argument('--'+n,required=True)
    for n in ('nm','pyocd','pack','boot-token-file','stream-output','schedule-contract','previous-trial-summary'):p.add_argument('--'+n)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for n in ('authorized-larger-exploration','energized-update-authorized','power-disconnected-confirmed',
        'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+n,action='store_true')
    a=p.parse_args();needed={'flash':('pyocd','pack'),'prepare':('nm','schedule_contract','previous_trial_summary'),
        'trial':('nm','schedule_contract','previous_trial_summary','boot_token_file','stream_output')}
    if any(not getattr(a,n) for n in needed[a.phase]):p.error('Missing phase evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
