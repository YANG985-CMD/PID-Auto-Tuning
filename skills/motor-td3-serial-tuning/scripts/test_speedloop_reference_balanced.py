"""Verify phase support and retained sequential gain limits; no hardware."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import speedloop_reference_balanced as subject


class BalanceTest(unittest.TestCase):
    def test_same_reference_has_baseline_and_probe_per_phase_in_every_boot(self):
        refs=(1000,950,1000,1050,1000,950,1000,1050)
        for pattern in subject.PATTERNS:
            self.assertEqual(len(pattern),32)
            self.assertEqual([pattern.count(i) for i in range(3)],[16,8,8])
            for ref in (950,1000,1050):
                indices=[i for i,v in enumerate(refs) if v==ref]
                for phase in range(4):
                    observed={pattern[4*i+phase]==0 for i in indices}
                    self.assertEqual(observed,{True,False})
                previous_phases={pattern[4*i-1]==0 if i else True for i in indices}
                self.assertEqual(previous_phases,{True,False})

    def test_actual_readback_and_old_single_step_rule_retained(self):
        for pattern in subject.PATTERNS:
            with subject.context(),subject.previous.context(pattern):
                runtime=subject.previous.base.previous
                policy=runtime.StagedProbe()
                for slot,level in enumerate(pattern):
                    kp,ki=policy.planned(6250+slot*500)
                    self.assertEqual(kp,subject.previous.base.SWITCH_LEVELS[level])
                    self.assertLessEqual(abs(kp-policy.actual),runtime.STEP/2+1e-9)
                    policy.observe(dict(kp=kp,ki=ki,enabled=True,applied_seq=slot+1))
                self.assertEqual(policy.planned(22250)[0],subject.previous.base.SWITCH_LEVELS[0])
                with self.assertRaises(RuntimeError):
                    policy.observe(dict(kp=.02,ki=ki,enabled=True,applied_seq=50))

    def test_old_pattern_restored_after_context(self):
        original=subject.previous.base.SWITCH_PATTERNS
        with subject.context():self.assertEqual(subject.previous.base.SWITCH_PATTERNS,subject.PATTERNS)
        self.assertEqual(subject.previous.base.SWITCH_PATTERNS,original)

    def test_undeclared_patterns_rejected_before_old_validator(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'contract.json'
            cfg=dict(gain_phase_design=subject.VERSION,pattern=list(subject.PATTERNS[0]),
                gain_phase_coverage_fit_split='predeclared independently in every boot',
                independent_performance_evaluation=False,actor_applied=False)
            a=SimpleNamespace(phase='prepare',schedule_contract=str(path),schedule_index=0)
            for key,value in (('gain_phase_design','wrong'),('pattern',[0]*32),('actor_applied',True)):
                wrong=dict(cfg);wrong[key]=value;path.write_text(json.dumps(wrong))
                with patch.object(subject.previous,'validate') as validator:
                    with self.assertRaises(ValueError):subject.validate(a)
                    validator.assert_not_called()
            path.write_text(json.dumps(cfg))
            with patch.object(subject.previous,'validate') as validator:
                subject.validate(a);validator.assert_called_once()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    output=Path(a.output);output.mkdir(parents=True,exist_ok=False);tempfile.tempdir=str(output)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BalanceTest))
    (output/'summary.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,
        hardware_accessed=False,protection_limits_changed=False,thermal_gate_modified=False))+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
