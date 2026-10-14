"""Offline directed coverage, local slew and startup/restore checks."""
from collections import Counter
from types import SimpleNamespace
import unittest
from speedloop_fixedref_probe import schedule,SEEDS,FixedProbe,KP_LEVELS,validate
from speedloop_motion_gain_trial import f32


class Tests(unittest.TestCase):
    def test_transition_coverage_and_baseline_tail(self):
        for seed in SEEDS:
            pattern=schedule(seed);counts=Counter(zip((0,*pattern[:-1]),pattern))
            self.assertEqual(counts,Counter({(i,j):5 for i in range(3) for j in range(3)}))
            self.assertEqual(Counter(pattern),Counter({0:15,1:15,2:15}))
            p=FixedProbe(seed);last=KP_LEVELS[0]
            for ms in range(0,24001,20):
                kp,ki=p.planned(ms);self.assertEqual(ki,f32(.00144));self.assertIn(kp,KP_LEVELS)
                self.assertLessEqual(abs(kp-last),.00027112);last=kp
                if ms<4000 or ms>=22000:self.assertEqual(kp,KP_LEVELS[0])
            self.assertEqual(len(p.decisions),45)

    def test_early_rejection(self):
        with self.assertRaises(ValueError):validate(SimpleNamespace(authorized_fixedref_capture=False))
        with self.assertRaises(ValueError):schedule(0)
        p=FixedProbe(SEEDS[0]);p.planned(4000)
        with self.assertRaises(RuntimeError):p.planned(4800)


if __name__=='__main__':unittest.main()
