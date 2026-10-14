import unittest
from types import SimpleNamespace
import speedloop_lower_commission as entry
from speedloop_stream_training import CausalStream,LOWER_GAINS,KI
from test_speedloop_stream_training import packet,proof


class Checks(unittest.TestCase):
    def test_permission_checked_before_any_path_or_hardware(self):
        with self.assertRaisesRegex(ValueError,'Direct human authorization'):
            entry.run(SimpleNamespace(operator_approved_lower_probe=False))
    def test_old_image_cannot_be_accepted(self):
        with self.assertRaises(ValueError):
            entry.validate(SimpleNamespace(operator_approved_lower_probe=True,authorized_lower_commission=True,
                phase='prepare',gain_mode='baseline',build='E:/simulink/_codex_tmp/td3-randomized-support-20261013/build-interior'))
    def test_each_reference_position_cell_has_both_arms(self):
        for position in range(9):
            labels=[entry.PATTERN[i] for i in range(45) if i%9==position]
            self.assertEqual(sorted([labels.count(0),labels.count(1)]),[2,3])
        p=entry.LowerProbe()
        for i,label in enumerate(entry.PATTERN):
            gain=p.planned(4000+400*i,mode='kp_probe')[0]
            self.assertEqual(gain,LOWER_GAINS[0] if label else LOWER_GAINS[1])
    def test_lower_actual_action_accepted_only_by_explicit_registry(self):
        p=packet(3);c=dict(type='gains',command_seq=1,kp=LOWER_GAINS[0],ki=KI,source_t_us=p['t_us'],expires_us=p['t_us']+100000)
        for allowed in (None,LOWER_GAINS):
            s=CausalStream() if allowed is None else CausalStream(allowed)
            for i in range(1,4):p=packet(i);s.telemetry(p,proof(p))
            if allowed is None:
                with self.assertRaises(ValueError):s.command(c,packet(3))
                continue
            s.command(c,packet(3));result=None
            for i in range(4,8):
                p=packet(i,kp=c['kp'],applied_seq=1,t_apply_us=c['source_t_us']+1000)
                result=s.telemetry(p,proof(p))
            self.assertAlmostEqual(result['physical_delta_action'][0],-.5,places=6)


if __name__=='__main__':unittest.main()
