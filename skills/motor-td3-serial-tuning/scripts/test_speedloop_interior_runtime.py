import unittest
from types import SimpleNamespace
import speedloop_interior as entry
from speedloop_stream_training import GAINS,INTERIOR_GAINS,CausalStream,KI
from test_speedloop_stream_training import packet,proof


class Checks(unittest.TestCase):
    def test_fixed_three_levels_and_stratification(self):
        self.assertEqual(entry.schedule(),entry.PATTERN)
        for phase in range(3):
            values=[v for i,v in enumerate(entry.PATTERN) if i%9//3==phase]
            self.assertEqual([values.count(i) for i in range(3)],[5,5,5])
        p=entry.InteriorProbe()
        for i,v in enumerate(entry.PATTERN):self.assertEqual(p.planned(4000+i*400,mode='kp_probe'),(INTERIOR_GAINS[v],KI))
        self.assertEqual(p.planned(22000,mode='kp_probe'),(GAINS[0],KI))
    def test_entry_scope_and_old_image_rejection(self):
        with self.assertRaises(ValueError):entry.run(SimpleNamespace(authorized_interior_commission=False))
        with self.assertRaises(ValueError):entry.validate(SimpleNamespace(authorized_interior_commission=True,
            phase='prepare',gain_mode='baseline',build='E:/simulink/_codex_tmp/td3-reactive-audit-20261013/build-24s-r2'))
    def test_midpoint_is_not_accepted_by_two_gain_stream(self):
        s=CausalStream()
        for i in range(1,4):p=packet(i);s.telemetry(p,proof(p))
        p=packet(3);c=dict(type='gains',command_seq=1,kp=INTERIOR_GAINS[1],ki=KI,source_t_us=p['t_us'],expires_us=p['t_us']+100000)
        with self.assertRaises(ValueError):s.command(c,p)
        s=CausalStream(INTERIOR_GAINS)
        for i in range(1,4):p=packet(i);s.telemetry(p,proof(p))
        s.command(c,packet(3));r=None
        for i in range(4,8):
            p=packet(i,kp=INTERIOR_GAINS[1],applied_seq=1,t_apply_us=c['source_t_us']+1000);r=s.telemetry(p,proof(p))
        self.assertAlmostEqual(r['physical_delta_action'][0],.25,places=6)


if __name__=='__main__':unittest.main()
