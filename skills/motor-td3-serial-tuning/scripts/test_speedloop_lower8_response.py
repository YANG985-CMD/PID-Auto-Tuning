"""Offline lower8 schedule, causal readback, Ki masking and no-authorization rejection."""
import unittest
from types import SimpleNamespace
from speedloop_lower8_response import Lower8Probe,PATTERN,KP_LEVELS,validate
from speedloop_stream_training import CausalStream,StreamObserver,LOWER8_GAINS,KI
from test_speedloop_stream_training import packet,proof


class Checks(unittest.TestCase):
    def test_holdout_cannot_claim_a_trainer(self):
        with self.assertRaises(ValueError):
            StreamObserver('E:/simulink/_codex_tmp/td3-lower8-20261013/uncreated',
                'E:/simulink/_codex_tmp/unused-ready.json',LOWER8_GAINS,capture_only=True)
        with self.assertRaises(ValueError):
            StreamObserver('E:/simulink/_codex_tmp/td3-lower8-20261013/uncreated',None,LOWER8_GAINS)

    def test_declared_support_and_restore(self):
        for cycle in range(5):self.assertEqual(set(PATTERN[cycle*3:cycle*3+3]),{0,1,2})
        for phase in range(3):self.assertEqual(sorted(PATTERN[phase::3].count(i) for i in range(3)),[1,2,2])
        p=Lower8Probe()
        for t in range(0,24001,20):
            kp,ki=p.planned(t);self.assertEqual(ki,KI);self.assertIn(kp,KP_LEVELS)
            if t<3850 or t>=22000:self.assertEqual(kp,KP_LEVELS[0])
        self.assertEqual(len(p.decisions),15)
        with self.assertRaises(ValueError):validate(SimpleNamespace(authorized_larger_kp_exploration=False))

    def test_real_ack_required_for_new_negative_support(self):
        s=CausalStream(LOWER8_GAINS)
        for n in range(1,4):p=packet(n);s.telemetry(p,proof(p))
        src=packet(3);c=dict(type='gains',command_seq=1,kp=KP_LEVELS[2],ki=KI,
            source_t_us=src['t_us'],expires_us=src['t_us']+100000)
        s.command(c,src);row=None
        for n in range(4,8):
            p=packet(n,kp=KP_LEVELS[2],applied_seq=1,t_apply_us=src['t_us']+1000)
            row=s.telemetry(p,proof(p))
        self.assertEqual(row['action_applied'],[KP_LEVELS[2],KI])
        self.assertAlmostEqual(row['physical_delta_action'][0],-.9875,places=6)
        for bad in (dict(c,command_seq=2,kp=.003),dict(c,command_seq=2,ki=KI*1.01)):
            with self.assertRaises(ValueError):s.command(bad,src)


if __name__=='__main__':unittest.main()
