import unittest
import json
import os
from pathlib import Path
import speedloop_upper8_plus2_longhold as runtime
import speedloop_upper8_continuous as previous

class Checks(unittest.TestCase):
    def test_context_and_fixed_ki_range_cap(self):
        with runtime.context():
            self.assertEqual(previous.PATTERNS,((0,2),(2,0)))
            self.assertEqual(previous.PLATEAU_MS,9000)
            self.assertEqual(previous.ANALYSIS_SETTLE_MS,7000)
            self.assertEqual(previous.IMAGE_SHA,'389a05e12240e37a24a58403df691adb3f20baa499756214a3c0af6f05a98cdf')
            self.assertEqual(previous.KI,previous.f32(.00144))
        self.assertEqual(previous.PLATEAU_MS,4500)
        self.assertEqual(previous.ANALYSIS_SETTLE_MS,200)
    def test_actual_ack_nine_second_holds_and_baseline_return(self):
        with runtime.context():
            for pattern in runtime.PATTERNS:
                p=previous.ContinuousUpperProbe(pattern)
                for ms in range(3900,23300,50):
                    kp,ki=p.planned(ms)
                    self.assertLessEqual(abs(kp-p.actual),previous.HOST_STEP+1e-9)
                    p.observe(dict(kp=kp,ki=ki))
                    if 4100<=ms<13000:self.assertEqual(kp,previous.LEVELS[pattern[0]])
                    if 13100<=ms<22000:self.assertEqual(kp,previous.LEVELS[pattern[1]])
                    if ms>=22100:self.assertEqual(kp,previous.LEVELS[0])
    def test_skipped_plateau_rejected(self):
        with runtime.context():
            p=previous.ContinuousUpperProbe(runtime.PATTERNS[0]);p.planned(4000)
            with self.assertRaises(RuntimeError):p.planned(31000-9000)
    def test_actual_stop_acknowledgement_controls_cooldown(self):
        root=Path(os.environ['MOTOR_TD3_TEST_ROOT'])/'cooldown-fixture';root.mkdir(parents=True,exist_ok=True)
        path=root/'summary.json'
        (root/'commands.jsonl').write_text(json.dumps(dict(type='stop',host_monotonic=100))+'\n')
        rows=[dict(enabled=False,fault=0,host_received_monotonic=1),
            dict(enabled=False,fault=0,host_received_monotonic=100.2)]
        (root/'telemetry.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.assertAlmostEqual(previous.confirmed_stop_cooldown(path,130.199),29.999)
        self.assertAlmostEqual(previous.confirmed_stop_cooldown(path,130.2),30)
        with self.assertRaises(ValueError):previous.confirmed_stop_cooldown(path,50)
        (root/'telemetry.jsonl').write_text(json.dumps(rows[0])+'\n')
        with self.assertRaises(ValueError):previous.confirmed_stop_cooldown(path,200)

if __name__=='__main__':unittest.main()
