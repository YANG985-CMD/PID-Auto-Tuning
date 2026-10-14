"""Check full planned switching clock, real bridges and retained limits."""
import unittest
import speedloop_upper8_switching as runtime
import speedloop_lower16_probe as staged
from speedloop_duration_review import overrides

class Checks(unittest.TestCase):
    def test_two_complete_patterns_fixed_exposure_and_step_bound(self):
        for pattern in runtime.PATTERNS:
            self.assertEqual(len(pattern),32)
            self.assertGreaterEqual(min(pattern.count(i) for i in (0,1,2)),10)
            with overrides(staged,LEVELS=runtime.previous.LEVELS,PATTERN=pattern,
                    LOWER16_GAINS=runtime.previous.LEVELS,STEP=runtime.previous.HOST_STEP,
                    PLATEAU_START_MS=6000,PLATEAU_MS=500,PLATEAU_END_MS=22000):
                p=staged.StagedProbe();changes=0
                for t in range(6000,22000,50):
                    old=p.actual;kp,ki=p.planned(t)
                    self.assertLessEqual(abs(kp-old),runtime.previous.HOST_STEP+1e-9)
                    changes+=kp!=old;p.observe(dict(kp=kp,ki=ki))
                    if t%500>=100:self.assertEqual(kp,staged.LEVELS[pattern[(t-6000)//500]])
                self.assertGreaterEqual(changes,35)
                kp,ki=p.planned(22000)
                self.assertLessEqual(abs(kp-p.actual),runtime.previous.HOST_STEP+1e-9)
    def test_capture_boundaries_restored_after_context(self):
        with runtime.context():self.assertEqual(runtime.previous.PLATEAU_MS,500)
        self.assertEqual(runtime.previous.PLATEAU_MS,2000)
    def test_every_slot_changes_requested_target(self):
        for pattern in runtime.PATTERNS:self.assertTrue(all(a!=b for a,b in zip(pattern,pattern[1:])))

if __name__=='__main__':unittest.main()
