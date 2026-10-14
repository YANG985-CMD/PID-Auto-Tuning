"""Offline readback/slew/schedule and capture-only boundary tests."""
import unittest
from unittest.mock import patch
from speedloop_lower16_probe import StagedProbe,LEVELS,KI,STEP,PATTERN,validate
from speedloop_stream_training import StreamObserver,LOWER16_GAINS

class Checks(unittest.TestCase):
    def test_all_plateaus_and_returns_preserve_old_slew(self):
        p=StagedProbe();actual=LEVELS[0];seen={};bridge_count=0
        for ms in range(0,23700,50):
            p.observe(dict(kp=actual,ki=KI));kp,ki=p.planned(ms)
            self.assertLessEqual(abs(kp-actual),STEP+1e-9);self.assertEqual(ki,KI)
            if 6000<=ms<22000:
                slot=(ms-6000)//2000
                if kp!=LEVELS[PATTERN[slot]]:bridge_count+=1
                else:seen[slot]=kp
            actual=kp
        self.assertEqual(seen,{s:LEVELS[v] for s,v in enumerate(PATTERN)})
        self.assertEqual(actual,LEVELS[0]);self.assertEqual(bridge_count,4)
    def test_missing_actual_bridge_cannot_release_lower_command(self):
        p=StagedProbe()
        for ms in (8000,8050,8100):self.assertEqual(p.planned(ms)[0],LEVELS[1])
        p.observe(dict(kp=LEVELS[1],ki=KI));self.assertEqual(p.planned(8150)[0],LEVELS[2])
    def test_prebegin_original_initial_gains_not_a_probe_ack(self):
        p=StagedProbe()
        p.observe(dict(enabled=False,applied_seq=0,kp=.002372299786657095,ki=.0011520000407472253))
        self.assertEqual(p.actual,LEVELS[0]);self.assertEqual(p.planned(0),(LEVELS[0],KI))
        with self.assertRaises(RuntimeError):
            p.observe(dict(enabled=True,applied_seq=1,kp=.002372299786657095,ki=.0011520000407472253))
    def test_restore_is_also_staged(self):
        p=StagedProbe();p.observe(dict(kp=LEVELS[2],ki=KI))
        self.assertEqual(p.planned(22000)[0],LEVELS[1])
        p.observe(dict(kp=LEVELS[1],ki=KI));self.assertEqual(p.planned(22050)[0],LEVELS[0])
    def test_unknown_gains_ki_and_missed_plateau_rejected(self):
        p=StagedProbe()
        with self.assertRaises(RuntimeError):p.observe(dict(kp=.0032,ki=KI))
        with self.assertRaises(RuntimeError):p.observe(dict(kp=LEVELS[0],ki=KI*1.01))
        with self.assertRaises(ValueError):p.planned(8000,1)
        p.planned(6000)
        with self.assertRaises(RuntimeError):p.planned(10000)
    def test_new_action_domain_cannot_attach_old_training_worker(self):
        with self.assertRaisesRegex(ValueError,'new action mapping'):
            StreamObserver('E:/simulink/_codex_tmp/unconsumed-test',None,LOWER16_GAINS,capture_only=False)
    def test_authorization_rejected_before_build_or_hardware(self):
        with patch('speedloop_lower16_probe.Path',side_effect=AssertionError('No file access expected')):
            with self.assertRaises(ValueError):validate(type('Args',(),{})())

if __name__=='__main__':unittest.main()
