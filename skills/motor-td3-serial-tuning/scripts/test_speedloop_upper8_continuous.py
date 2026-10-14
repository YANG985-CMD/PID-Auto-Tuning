"""Host tests for exact probes; no CAN or debug attachment."""
import unittest
import speedloop_upper8_continuous as runtime
from speedloop_stream_training import CausalStream,StreamObserver,UPPER8_GAINS,KI
from test_speedloop_stream_training import packet,proof

class Checks(unittest.TestCase):
    def test_complementary_order_and_ack_slew(self):
        self.assertEqual(runtime.PATTERNS[1],tuple(reversed(runtime.PATTERNS[0])))
        for pattern in runtime.PATTERNS:
            p=runtime.ContinuousUpperProbe(pattern)
            for ms in range(3900,23300,50):
                kp,ki=p.planned(ms);self.assertLessEqual(abs(kp-p.actual),runtime.HOST_STEP+1e-9)
                p.observe(dict(kp=kp,ki=ki))
                if 4100<=ms<22000:
                    slot=(ms-4000)//4500
                    if (ms-4000)%4500>=100:self.assertEqual(kp,runtime.LEVELS[pattern[slot]])
                if ms>=22100:self.assertEqual(kp,runtime.LEVELS[0])
    def test_wait_for_ack_bridge(self):
        p=runtime.ContinuousUpperProbe(runtime.PATTERNS[1])
        self.assertEqual(p.planned(4000)[0],runtime.LEVELS[4])
        self.assertEqual(p.planned(4050)[0],runtime.LEVELS[4])
        p.observe(dict(kp=runtime.LEVELS[4],ki=KI))
        self.assertEqual(p.planned(4100)[0],runtime.LEVELS[8])
    def test_unknown_actual_ki_missed_slot(self):
        p=runtime.ContinuousUpperProbe(runtime.PATTERNS[0]);p.planned(4000)
        with self.assertRaises(RuntimeError):p.planned(13000)
        with self.assertRaises(RuntimeError):p.observe(dict(kp=runtime.f32(.0036),ki=KI))
        with self.assertRaises(ValueError):p.planned(4000,1)
    def test_capture_only_and_old_profile_rejection(self):
        with self.assertRaises(ValueError):StreamObserver('unused',None,runtime.LEVELS,capture_only=False)
        s=CausalStream(UPPER8_GAINS);source=packet(3)
        c=dict(type='gains',command_seq=1,kp=runtime.LEVELS[6],ki=KI,
            source_t_us=source['t_us'],expires_us=source['t_us']+100000)
        with self.assertRaises(ValueError):s.command(c,source)
    def test_actual_dense_readback_windows(self):
        s=CausalStream(runtime.LEVELS)
        for n in range(1,4):p=packet(n,kp=runtime.LEVELS[2]);s.telemetry(p,proof(p))
        source=p;c=dict(type='gains',command_seq=1,kp=runtime.LEVELS[6],ki=KI,
            source_t_us=p['t_us'],expires_us=p['t_us']+100000)
        s.command(c,source)
        for n in range(4,8):
            p=packet(n,kp=runtime.LEVELS[6],applied_seq=1,t_apply_us=source['t_us']+1000)
            r=s.telemetry(p,proof(p))
        self.assertTrue(r['action_mapping_redefinition_required'])
        self.assertEqual(r['action_applied'],[runtime.LEVELS[6],KI]);self.assertFalse(r['actor_applied'])

if __name__=='__main__':unittest.main()
