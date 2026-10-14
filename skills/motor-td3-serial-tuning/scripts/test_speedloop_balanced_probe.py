import unittest
from speedloop_balanced_probe import PATTERN,BalancedProbe,schedule
from speedloop_motion_gain_trial import f32


class Checks(unittest.TestCase):
    def test_balance_and_reproducible_predeclared_assignment(self):
        self.assertEqual(list(PATTERN),schedule());self.assertEqual(len(PATTERN),45)
        for phase in range(3):
            values=[v for i,v in enumerate(PATTERN) if i%9//3==phase]
            self.assertEqual(values.count(0),7);self.assertEqual(values.count(1),8)
    def test_startup_tail_and_exact_gain_ki_bounds(self):
        p=BalancedProbe()
        self.assertEqual(p.planned(3999,mode='kp_probe'),(f32(.003389),f32(.00144)))
        for i,v in enumerate(PATTERN):
            self.assertEqual(p.planned(4000+i*400,mode='kp_probe'),
                             (f32(.00352456 if v else .003389),f32(.00144)))
        self.assertEqual(p.planned(22000,mode='kp_probe'),(f32(.003389),f32(.00144)))
        with self.assertRaises(ValueError):p.planned(4000,1,'kp_probe')
    def test_missing_slot_rejected(self):
        p=BalancedProbe();p.planned(4000,mode='kp_probe')
        with self.assertRaises(RuntimeError):p.planned(4800,mode='kp_probe')


if __name__=='__main__':unittest.main()
