"""Missing-pair schedule and original firmware slew guard, no hardware."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import speedloop_reference_complete_pairs as subject


class PairTest(unittest.TestCase):
    def test_all_directed_changes_in_every_reference(self):
        refs=(1000,950,1000,1050,1000,950,1000,1050)
        required={(a,b) for a in range(3) for b in range(3) if a!=b}
        for pattern in subject.PATTERNS:
            self.assertEqual(len(pattern),32);pairs={ref:set() for ref in set(refs)};previous=0
            for i,target in enumerate(pattern):pairs[refs[i//4]].add((previous,target));previous=target
            for measured in pairs.values():self.assertTrue(required<=measured)
            self.assertTrue(all(pattern.count(i)>=9 for i in range(3)))

    def test_direct_low_high_keeps_original_full_step_limit(self):
        for pattern in subject.PATTERNS:
            with subject.context(),subject.previous.context(pattern):
                runtime=subject.previous.base.previous;policy=runtime.StagedProbe();pairs=set()
                for slot,level in enumerate(pattern):
                    before=policy.actual;kp,ki=policy.planned(6250+500*slot)
                    self.assertEqual(kp,subject.previous.base.SWITCH_LEVELS[level])
                    self.assertLessEqual(abs(kp-before),runtime.STEP+1e-9)
                    pairs.add((before,kp));policy.observe(dict(kp=kp,ki=ki,enabled=True,applied_seq=slot+1))
                low,high=subject.previous.base.SWITCH_LEVELS[1:]
                self.assertIn((low,high),pairs);self.assertIn((high,low),pairs)
                self.assertEqual(policy.planned(22250)[0],subject.previous.base.SWITCH_LEVELS[0])
                with self.assertRaises(RuntimeError):policy.observe(dict(kp=.02,ki=ki,enabled=True,applied_seq=99))

    def test_stale_slot_stops_and_context_restores(self):
        original=subject.previous.base.SWITCH_PATTERNS
        with subject.context(),subject.previous.context(subject.PATTERNS[0]):
            policy=subject.previous.base.previous.StagedProbe();policy.planned(6250)
            with self.assertRaises(RuntimeError):policy.planned(7250)
        self.assertEqual(subject.previous.base.SWITCH_PATTERNS,original)

    def test_undeclared_patterns_rejected_before_hardware_delegate(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'contract.json'
            cfg=dict(gain_pair_design=subject.VERSION,pattern=list(subject.PATTERNS[0]),
                firmware_single_kp_step_limit=.00027112,same_gain_levels_and_firmware_limits=True,
                new_direct_low_high_pairs_are_experimental=True,independent_performance_evaluation=False,actor_applied=False)
            args=SimpleNamespace(phase='prepare',schedule_contract=str(path),schedule_index=0)
            for key,value in (('pattern',[0]*32),('firmware_single_kp_step_limit',.0003),
                ('same_gain_levels_and_firmware_limits',False),('actor_applied',True)):
                wrong=dict(cfg);wrong[key]=value;path.write_text(json.dumps(wrong))
                with patch.object(subject.previous,'validate') as validator:
                    with self.assertRaises(ValueError):subject.validate(args)
                    validator.assert_not_called()
            path.write_text(json.dumps(cfg))
            with patch.object(subject.previous,'validate') as validator:
                subject.validate(args);validator.assert_called_once()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    output=Path(a.output);output.mkdir(parents=True,exist_ok=False);tempfile.tempdir=str(output)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PairTest))
    (output/'summary.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,
        hardware_accessed=False,firmware_limits_changed=False,thermal_gate_modified=False))+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
