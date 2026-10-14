import copy,math,unittest
from audit_speedloop_response_horizon import integral

class Checks(unittest.TestCase):
    def fixture(self):
        return [dict(edge=i+1,t_us=10*i,period_us=10,rpm=1000+10*i,valid=True,model_stage=4) for i in range(10)]
    def test_fractional_held_time_raw_metric(self):
        q=integral(self.fixture(),5,25)
        self.assertEqual(q['duration_us'],20)
        self.assertEqual(q['mse_rpm2'],150)
        self.assertAlmostEqual(q['raw_Hall_RMSE_rpm'],math.sqrt(150))
        self.assertEqual(q['peak_raw_Hall_speed_rpm'],1020)
        self.assertEqual(q['mean_error_rpm'],-10)
    def test_future_value_outside_bin_unused(self):
        a=self.fixture();b=copy.deepcopy(a);b[3]['rpm']=1e9
        self.assertEqual(integral(a,5,25),integral(b,5,25))
    def test_gaps_invalid_stage_and_incomplete_coverage(self):
        for change in ('edge','clock','stage','valid','early','late','empty'):
            with self.subTest(change=change):
                a=self.fixture();lo=5;hi=25
                if change=='edge':a[1]['edge']=5
                if change=='clock':a[1]['period_us']=11
                if change=='stage':a[1]['model_stage']=3
                if change=='valid':a[1]['valid']=False
                if change=='early':lo=-1
                if change=='late':hi=91
                if change=='empty':hi=lo
                with self.assertRaises(ValueError):integral(a,lo,hi)

if __name__=='__main__':unittest.main()
