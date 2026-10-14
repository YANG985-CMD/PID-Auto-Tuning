"""Exact v25 baseline/+4% nine-second holds, late score, no Actor."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import speedloop_upper8_continuous as previous
from speedloop_duration_review import overrides

PATTERNS=((0,4),(4,0))
VERSION='upper8-continuous-plus4-longhold-late-score-v1'

@contextmanager
def context():
    with overrides(previous,PATTERNS=PATTERNS,PLATEAU_START_MS=4000,PLATEAU_MS=9000,
        PLATEAU_END_MS=22000,ANALYSIS_SETTLE_MS=7000,ANALYSIS_END_MARGIN_MS=200,VERSION=VERSION):
        yield

def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Same reviewed v25 only; no firmware change')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    if (cfg.get('hold_design')!=VERSION or cfg.get('gain_hold_seconds')!=9
        or cfg.get('post_actual_apply_wait_seconds')!=7
        or cfg.get('physical_behavior_probe_not_frozen_actor') is not True
        or cfg.get('probe_mode')!='upper8-continuous-plus4-longhold'
        or cfg.get('independent_performance_evaluation') is not True):
        raise ValueError('Predeclared complementary long hold and late score required')
    if a.schedule_index==0:
        path=Path(a.recovery_readonly);state=json.loads(path.read_text(encoding='utf-8'))
        if (not getattr(a,'fault_recovery_authorized',False)
            or cfg.get('fresh_human_fault_recovery_authorization') is not True
            or cfg.get('recovery_readonly_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()
            or state.get('full_readback_sha256')!=previous.IMAGE_SHA
            or not state.get('core_halted') or state.get('Motor_state')!=0
            or state.get('irq_fault')!=1 or state.get('tx_fault')!=0
            or any(state.get(k) is not False for k in ('hardware_written','reset','resume'))):
            raise ValueError('Exact retained fault and direct human recovery authorization required')
        r=state['registers']
        if (r['tim1_ccer']&0x555 or r['tim1_bdtr']&0x8000
            or r['gpioa_odr']&0x700 or r['gpiob_odr']&0xe000
            or r['gpioa_moder']&0x3f0000!=0x150000 or r['gpiob_moder']&0xfc000000!=0x54000000):
            raise ValueError('Recovery snapshot must show all six phase GPIO outputs low')
    with context():return previous.validate(a)

def run(a):
    validate(a)
    with context():result=previous.run(a)
    result.update(hold_design=VERSION,gain_hold_seconds=9,post_actual_apply_wait_seconds=7,
        physical_behavior_probe_not_frozen_actor=True,firmware_unchanged=True,
        actor_applied=False,candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result
