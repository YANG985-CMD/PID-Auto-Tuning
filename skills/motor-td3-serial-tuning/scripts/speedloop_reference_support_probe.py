"""Exact v26 follow-up: predeclared missing reference/source/target captures."""
import argparse
from pathlib import Path
import speedloop_upper8_reference_v26 as base
from speedloop_duration_review import overrides

IDENTITY=base.IDENTITY;IMAGE_SHA=base.IMAGE_SHA;LEVELS=base.LEVELS;KI=base.KI
REFERENCE_PROFILE=base.REFERENCE_PROFILE;reference_matches=base.reference_matches;sha=base.sha
VERSION='upper8-reference-conditional-support-v26-v2'
PATTERNS=((0,2,0,4,6,4,0,4,2,4,6,6,8,6,2,4,6,2,6,8,6,8,8,4,8,4,0,0,0,2,2,0),
          (0,2,0,4,0,4,2,6,6,4,6,2,4,2,0,2,2,4,2,0,2,4,8,6,2,6,8,4,8,6,4,0))
DESIGN_REPLAY_SHA='2d5fb5ea6355897be11916fbf5f80eff855f1ae415c37099a5fc00fc24a3902e'
original_expected=base.expected_schedule


def expected_schedule(index):
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION):
        cfg=original_expected(index)
    cfg.update(design_replay_summary_sha256=DESIGN_REPLAY_SHA,
        purpose='Fill observed reference/source/actual-target category gaps; no reward-based policy selection',
        anticipated_coverage_is_not_actual_evidence=True,firmware_image_changed=False,
        scheduled_probe_source_sha256=sha(Path(__file__)),
        planned_reference_target_categories=[list(x) for x in sorted({
            (base.reference_rpm((6250+500*k)*1000),level) for k,level in enumerate(PATTERNS[index])})])
    return cfg


def validate(args):
    if args.phase not in ('prepare','trial'):
        raise ValueError('Reuse the exact existing v26 image; no flash or qualification')
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION,expected_schedule=expected_schedule):
        return base.validate(args)


def run(args):
    validate(args)
    with overrides(base,PATTERNS=PATTERNS,VERSION=VERSION,expected_schedule=expected_schedule):
        result=base.run(args)
    result.update(conditional_support_probe=True,design_replay_summary_sha256=DESIGN_REPLAY_SHA,
        scheduled_probe_source_sha256=sha(Path(__file__)),candidate_admission=False)
    (Path(args.output)/'summary.json').write_text(__import__('json').dumps(result,indent=2,allow_nan=False)+'\n')
    return result
