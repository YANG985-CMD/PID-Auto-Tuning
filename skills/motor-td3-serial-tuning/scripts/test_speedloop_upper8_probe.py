"""Host staging and capture segregation tests; no hardware imports."""
import unittest
from unittest.mock import patch
import speedloop_upper8_probe as runtime
import speedloop_lower16_probe as staged
from speedloop_duration_review import overrides
from speedloop_stream_training import CausalStream,StreamObserver,UPPER8_GAINS,KI
from test_speedloop_stream_training import packet,proof

class Checks(unittest.TestCase):
    def test_complementary_order_same_exposure(self):
        self.assertEqual(runtime.PATTERNS[1],(2,0,0,2,2,0,0,2))
        for i in range(8):self.assertEqual(runtime.PATTERNS[0][i]+runtime.PATTERNS[1][i],2)
        for p in runtime.PATTERNS:
            self.assertEqual(p.count(0),4);self.assertEqual(p.count(2),4)
    def test_bridge_requires_actual_readback_in_both_directions(self):
        with overrides(staged,LEVELS=runtime.LEVELS,PATTERN=runtime.PATTERN,
                LOWER16_GAINS=UPPER8_GAINS,STEP=runtime.HOST_STEP):
            s=staged.StagedProbe()
            for t,expected in ((8000,1),(8050,1)):
                self.assertEqual(s.planned(t)[0],UPPER8_GAINS[expected])
            s.observe(dict(kp=UPPER8_GAINS[1],ki=KI))
            self.assertEqual(s.planned(8100)[0],UPPER8_GAINS[2])
            s.observe(dict(kp=UPPER8_GAINS[2],ki=KI))
            s.planned(10000)
            self.assertEqual(s.planned(12000)[0],UPPER8_GAINS[1])
            s.observe(dict(kp=UPPER8_GAINS[1],ki=KI))
            self.assertEqual(s.planned(12050)[0],UPPER8_GAINS[0])
    def test_missing_slot_unknown_gain_and_ki_rejected(self):
        with overrides(staged,LEVELS=runtime.LEVELS,PATTERN=runtime.PATTERN,
                LOWER16_GAINS=UPPER8_GAINS,STEP=runtime.HOST_STEP):
            s=staged.StagedProbe();s.planned(6000)
            with self.assertRaises(RuntimeError):s.planned(10000)
            with self.assertRaises(RuntimeError):s.observe(dict(kp=.0037,ki=KI))
            with self.assertRaises(ValueError):s.planned(6000,1)
    def test_old_profile_rejects_new_gain(self):
        s=CausalStream();source=packet(3)
        c=dict(type='gains',command_seq=1,kp=UPPER8_GAINS[2],ki=KI,source_t_us=source['t_us'],expires_us=source['t_us']+100000)
        with self.assertRaises(ValueError):s.command(c,source)
    def test_new_profile_requires_capture_only(self):
        with self.assertRaises(ValueError):StreamObserver('unused',None,UPPER8_GAINS,capture_only=False)
    def test_new_real_ack_window_marks_mapping_review(self):
        s=CausalStream(UPPER8_GAINS)
        for n in range(1,4):p=packet(n,kp=UPPER8_GAINS[1]);s.telemetry(p,proof(p))
        source=p;c=dict(type='gains',command_seq=1,kp=UPPER8_GAINS[2],ki=KI,
            source_t_us=p['t_us'],expires_us=p['t_us']+100000)
        s.command(c,source);r=None
        for n in range(4,8):
            p=packet(n,kp=UPPER8_GAINS[2],applied_seq=1,t_apply_us=source['t_us']+1000)
            r=s.telemetry(p,proof(p))
        self.assertIsNotNone(r);self.assertTrue(r['action_mapping_redefinition_required'])
        self.assertFalse(r['deployment_allowed']);self.assertEqual(r['action_applied'],[UPPER8_GAINS[2],KI])

if __name__=='__main__':unittest.main()
