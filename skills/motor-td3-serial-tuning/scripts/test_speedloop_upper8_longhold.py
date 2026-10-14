"""Exercise long holds, ACK bridges and end-of-trial baseline restoration."""
import unittest
import speedloop_upper8_longhold as runtime
import speedloop_lower16_probe as staged
from speedloop_duration_review import overrides

class Checks(unittest.TestCase):
    def test_planned_holds_ack_and_original_step_limit(self):
        for pattern in runtime.PATTERNS:
            with overrides(staged,LEVELS=runtime.previous.LEVELS,PATTERN=pattern,
                LOWER16_GAINS=runtime.previous.LEVELS,STEP=runtime.previous.HOST_STEP,
                PLATEAU_START_MS=4000,PLATEAU_MS=9000,PLATEAU_END_MS=22000):
                p=staged.StagedProbe();self.assertEqual(p.planned(3999)[0],staged.LEVELS[0])
                for ms in range(4000,23000,50):
                    kp,ki=p.planned(ms);self.assertLessEqual(abs(kp-p.actual),runtime.previous.HOST_STEP+1e-9)
                    p.observe(dict(kp=kp,ki=ki))
                    if 4150<=ms<13000:self.assertEqual(kp,staged.LEVELS[pattern[0]])
                    if 13150<=ms<22000:self.assertEqual(kp,staged.LEVELS[pattern[1]])
                    if ms>=22150:self.assertEqual(kp,staged.LEVELS[0])
    def test_late_scoring_and_context_restoration(self):
        with runtime.context():
            self.assertEqual(runtime.previous.PATTERNS,((0,2),(2,0)))
            self.assertEqual(runtime.previous.PLATEAU_START_MS,4000)
            self.assertEqual(runtime.previous.PLATEAU_MS,9000)
            self.assertEqual(runtime.previous.ANALYSIS_SETTLE_MS,7000)
        self.assertEqual(runtime.previous.PLATEAU_MS,2000)
        self.assertEqual(runtime.previous.PLATEAU_START_MS,6000)
    def test_same_gain_range_ki_and_firmware(self):
        self.assertEqual(runtime.previous.IDENTITY,'g431-speedloop-pi-upper8-24s-v24')
        self.assertEqual(runtime.previous.IMAGE_SHA,'42d39dcc54bae0f088a1ec0653ffdb7e9c04bae82342a4f7dd85191666d71f4f')
        self.assertEqual(runtime.previous.staged.KI,runtime.previous.f32(.00144))

if __name__=='__main__':unittest.main()
