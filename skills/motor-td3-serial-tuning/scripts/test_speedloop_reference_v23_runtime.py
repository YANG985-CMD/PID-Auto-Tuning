"""Exact-image/predeclared reference schedule checks without opening hardware."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import speedloop_reference_v23 as subject


class RuntimeTest(unittest.TestCase):
    def test_reference_tolerance_is_bounded(self):
        for ms in range(0,24001,17):
            self.assertTrue(subject.reference_matches(ms,subject.reference_rpm(ms*1000)))
        self.assertTrue(subject.reference_matches(8000,1000))
        self.assertTrue(subject.reference_matches(8000,950))
        self.assertFalse(subject.reference_matches(8010,1000))
        for rpm in (0,900,1100,1800):self.assertFalse(subject.reference_matches(10000,rpm))

    def test_shift_keeps_actual_switches_separate_from_reference_edges(self):
        with subject.context(subject.base.SWITCH_PATTERNS[0]):
            policy=subject.base.previous.StagedProbe();changes=0
            for slot,level in enumerate(subject.base.SWITCH_PATTERNS[0]):
                elapsed=6250+slot*500;prior=policy.actual;kp,ki=policy.planned(elapsed)
                self.assertEqual(kp,subject.base.SWITCH_LEVELS[level])
                self.assertLessEqual(abs(kp-prior),subject.base.previous.STEP/2+1e-9)
                if kp!=prior:
                    changes+=1
                    self.assertGreaterEqual(min(abs(elapsed-boundary) for boundary in range(6000,22001,2000)),250)
                policy.observe(dict(kp=kp,ki=ki,enabled=True,applied_seq=slot+1))
            kp,ki=policy.planned(22250);changes+=kp!=policy.actual
            self.assertEqual(changes,32);self.assertEqual(kp,subject.base.SWITCH_LEVELS[0])

    def test_requires_exact_contract_before_delegation(self):
        basecfg=dict(reference_profile='exogenous-v23-950-1000-1050',
            reference_pattern_rpm=[1000,950,1000,1050,1000,950,1000,1050],
            reference_start_ms=6000,reference_slot_ms=2000,reference_finish_ms=22000,
            plateau_start_ms=6250,gain_switches_offset_from_reference_ms=250,
            old_fixed_reference_training_allowed=False,old_lower16_training_allowed=False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'schedule.json'
            args=SimpleNamespace(authorized_reference_steps=True,phase='prepare',build=self.build,
                adapter_checks=self.checks,schedule_contract=str(path))
            for key,value in (('plateau_start_ms',6000),('reference_slot_ms',1000),
                ('old_fixed_reference_training_allowed',True),('reference_profile','arbitrary')):
                cfg=dict(basecfg);cfg[key]=value;path.write_text(json.dumps(cfg))
                with patch.object(subject.base,'validate') as delegate:
                    with self.assertRaises(ValueError):subject.validate(args)
                    delegate.assert_not_called()
            path.write_text(json.dumps(basecfg))
            with patch.object(subject.base,'validate') as delegate:
                subject.validate(args);delegate.assert_called_once()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--build',required=True);p.add_argument('--checks',required=True)
    a=p.parse_args();output=Path(a.output);output.mkdir(parents=True,exist_ok=False);tempfile.tempdir=str(output)
    RuntimeTest.build=a.build;RuntimeTest.checks=a.checks
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTest))
    (output/'summary.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,hardware_accessed=False))+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
