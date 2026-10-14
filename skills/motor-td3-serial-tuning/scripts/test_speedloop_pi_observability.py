import unittest
from audit_speedloop_pi_action_observability import nominal_increment

class Checks(unittest.TestCase):
    def test_no_instantaneous_bump(self):
        for error in (-1000,-60,0,60,1000):self.assertEqual(nominal_increment(.00013556,error,error),0)
    def test_gain_times_error_change_and_direction(self):
        self.assertAlmostEqual(nominal_increment(.00013556,60,0),.0081336)
        self.assertAlmostEqual(nominal_increment(-.00013556,60,0),-.0081336)
        self.assertAlmostEqual(nominal_increment(.00006778,20,30),-.0006778)
    def test_zero_gain_change_has_no_effect(self):
        self.assertEqual(nominal_increment(0,123,456),0)

if __name__=='__main__':unittest.main()
