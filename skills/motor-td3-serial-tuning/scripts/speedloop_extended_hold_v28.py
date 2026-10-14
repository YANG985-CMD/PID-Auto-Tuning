"""Longer measured responses using the existing exact v28 image and old gain range.

Two predetermined 24-second captures, fixed Ki, no Actor, no new firmware.
"""
import speedloop_lower31_v28 as base
from speedloop_duration_review import overrides

VERSION='extended-two-second-holds-exact-v28-v1'
REFERENCE_PROFILE='exogenous-v28-extended-holds-950-1000-1050'
PATTERNS=(tuple(i for k in (8,7,6,5,4,5,6,7) for i in [k]*4),
          tuple(i for k in (8,10,12,14,16,14,12,10) for i in [k]*4))
IDENTITY=base.IDENTITY;IMAGE_SHA=base.IMAGE_SHA;LEVELS=base.LEVELS;KI=base.KI
BASE_INDEX=base.BASE_INDEX;PLATEAU_START_MS=base.PLATEAU_START_MS
PLATEAU_END_MS=base.PLATEAU_END_MS;PLATEAU_MS=base.PLATEAU_MS
HALL_READ_PROFILE=base.HALL_READ_PROFILE;reference_matches=base.reference_matches
sha=base.sha
ORIGINAL_SCHEDULE=base.expected_schedule

class ExtendedProbe(base.ReferenceProbe):
    def observe(self,t):
        if t.get('enabled',True) and t.get('applied_seq',1) and t['kp']<LEVELS[4]:
            raise RuntimeError('Long-response capture stays in the previously tried lower16/upper8 range')
        super().observe(t)
    def planned(self,*args,**kwargs):
        result=super().planned(*args,**kwargs)
        if not LEVELS[4]<=result[0]<=LEVELS[16] or result[1]!=KI:
            raise RuntimeError('Long-response command outside declared old gain range')
        return result

def expected_schedule(index):
    with overrides(base,VERSION=VERSION,REFERENCE_PROFILE=REFERENCE_PROFILE,PATTERNS=PATTERNS):
        cfg=ORIGINAL_SCHEDULE(index)
    cfg.update(extended_hold_capture=True,nominal_target_hold_ms=2000,
        applied_gain_domain=[LEVELS[4],LEVELS[16]],new_firmware_required=False,
        existing_v28_FOC_PI_ADC_Hall_reference_and_guards_unchanged=True,
        one_second_response_view_requires_new_offline_audit=True)
    return cfg

def run(a):
    if not getattr(a,'authorized_extended_hold_capture',False):
        raise ValueError('Finite extended-hold batch scope required')
    if a.phase not in ('prepare','trial'):
        raise ValueError('Existing image only; no flash or new qualification phase')
    with overrides(base,VERSION=VERSION,REFERENCE_PROFILE=REFERENCE_PROFILE,PATTERNS=PATTERNS,
        ReferenceProbe=ExtendedProbe,expected_schedule=expected_schedule):
        result=base.run(a)
    result.update(extended_hold_capture=True,nominal_target_hold_ms=2000,
        applied_gain_domain=[LEVELS[4],LEVELS[16]],new_firmware_written=False,
        new_training_data_admission=False)
    # Preserve base.run's authoritative shutdown and exact-image evidence.
    import json
    from pathlib import Path
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result
