"""Exact v26 independent +4% hold capture for qualified 300ms response data."""
import json
from pathlib import Path
import speedloop_upper8_reference_v26 as base
from speedloop_duration_review import overrides

IDENTITY=base.IDENTITY;IMAGE_SHA=base.IMAGE_SHA;LEVELS=base.LEVELS;KI=base.KI
REFERENCE_PROFILE=base.REFERENCE_PROFILE;reference_matches=base.reference_matches;sha=base.sha
VERSION='upper8-reference-independent-plus4-longhold-v26-v3'
PATTERNS=((0,)+(4,)*30+(0,),)*2
original_expected=base.expected_schedule

def expected_schedule(index):
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION):cfg=original_expected(index)
    cfg.update(purpose='Independent +4% actual hold support for a 300ms response view',
        maximum_commanded_kp=LEVELS[4],fixed_target_hold_begin_ms=6750,fixed_target_hold_end_ms=21750,
        planned_reference_target_categories=[list(x) for x in sorted({
            (base.reference_rpm((6250+500*k)*1000),level) for k,level in enumerate(PATTERNS[index])})],
        source_sampling_refusal='reference-joint-support-20261014/response-300ms/sampling-preflight-refusal.json',
        sampling_gate_relaxed=False,firmware_image_changed=False,
        scheduled_probe_source_sha256=sha(Path(__file__)))
    return cfg

def validate(args):
    if args.phase not in ('prepare','trial'):raise ValueError('Only exact existing-image bounded capture')
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION,expected_schedule=expected_schedule):return base.validate(args)

def run(args):
    validate(args)
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION,expected_schedule=expected_schedule):result=base.run(args)
    result.update(independent_plus4_longhold_capture=True,maximum_commanded_kp=LEVELS[4],
        scheduled_probe_source_sha256=sha(Path(__file__)),candidate_admission=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result
