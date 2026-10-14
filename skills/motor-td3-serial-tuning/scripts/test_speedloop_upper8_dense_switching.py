import unittest
from types import SimpleNamespace
import speedloop_upper8_dense_switching as runtime

class Checks(unittest.TestCase):
    def test_all_reachable_pairs_both_directions(self):
        expected={(v,w) for v in (0,2,4,6,8) for w in (0,2,4,6,8) if 0<abs(v-w)<=4}
        self.assertEqual(len(expected),14)
        for pattern in runtime.PATTERNS:
            pairs=runtime.planned_pair_counts(pattern)
            self.assertEqual(len(pattern),32);self.assertEqual(pattern[0],0);self.assertEqual(pattern[-1],0)
            self.assertEqual(set(pairs),expected);self.assertGreaterEqual(min(pairs.values()),2)
    def test_actual_ack_rate_boundary_and_restoration(self):
        p=runtime.previous
        with runtime.context():
            for pattern in runtime.PATTERNS:
                probe=p.ContinuousUpperProbe(pattern)
                for ms in range(3900,23400,50):
                    kp,ki=probe.planned(ms)
                    self.assertEqual(ki,p.KI)
                    self.assertLessEqual(abs(kp-probe.actual),p.HOST_STEP+1e-9)
                    self.assertGreaterEqual(kp,p.LEVELS[0]);self.assertLessEqual(kp,p.LEVELS[8])
                    probe.observe(dict(kp=kp,ki=ki))
                    if 6000<=ms<22000:self.assertEqual(kp,p.LEVELS[pattern[(ms-6000)//500]])
                    else:self.assertEqual(kp,p.LEVELS[0])
            self.assertEqual(p.IMAGE_SHA,'389a05e12240e37a24a58403df691adb3f20baa499756214a3c0af6f05a98cdf')
        self.assertEqual(p.PLATEAU_MS,4500);self.assertEqual(p.ANALYSIS_SETTLE_MS,200)
    def test_missed_slot_rejected(self):
        with runtime.context():
            probe=runtime.previous.ContinuousUpperProbe(runtime.PATTERNS[0]);probe.planned(6000)
            with self.assertRaises(RuntimeError):probe.planned(7500)
    def test_no_authority_and_no_flash(self):
        for phase in ('flash','prepare','trial'):
            with self.assertRaises(ValueError):runtime.validate(SimpleNamespace(phase=phase))

if __name__=='__main__':unittest.main()
