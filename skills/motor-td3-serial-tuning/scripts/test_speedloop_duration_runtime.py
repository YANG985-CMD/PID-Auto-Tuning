"""Offline checks: no extension by old approval, no Actor and bounded heartbeats."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import speedloop_duration_review as review
import speedloop_motion_gain_trial as trial


class Checks(unittest.TestCase):
    def test_old_approval_cannot_extend_duration(self):
        with self.assertRaises(ValueError):review.validate(SimpleNamespace(authorized_single_5s_review=False))

    def test_exact_image_manifest_and_contents_required(self):
        info={'build_id':review.IDENTITY,'passed':True,'bin_sha256':review.IMAGE_SHA,
            'duration_review':{'mode':'single fixed baseline PI; no Actor or gain exploration',
                               'maximum_motion_seconds':5}}
        args=SimpleNamespace(authorized_single_5s_review=True,build='unused')
        with patch.object(Path,'read_text',return_value=json.dumps(info)), \
             patch.object(Path,'read_bytes',return_value=b'wrong image'):
            with self.assertRaises(ValueError):review.validate(args)

    def test_probe_and_actor_rejected_before_hardware(self):
        for options in ({'apply_shadow_kp':True},{'shadow_port':55000},
                        {'ki_probe_sign':1},{'gain_mode':'kp_probe'}):
            args=SimpleNamespace(phase='trial',**options)
            with patch.object(review,'validate'),patch.object(trial,'trial') as live:
                with self.assertRaises(ValueError):review.run(args)
                live.assert_not_called()

    def test_runtime_override_restored_even_after_failure(self):
        old=trial.STOP_SECONDS
        with self.assertRaises(RuntimeError):
            with review.overrides(trial,STOP_SECONDS=4.8):raise RuntimeError('injected')
        self.assertEqual(trial.STOP_SECONDS,old)
        self.assertEqual(trial.MAX_MOTION_SECONDS,3)
        self.assertIsNone(trial.TIMING_EVIDENCE_SYMBOL)

    def test_extended_heartbeat_command_budget_and_stop_reserve(self):
        with review.overrides(trial,STOP_SECONDS=4.8,GAIN_CUTOFF_SECONDS=4.7,
            FINAL_GAIN_SECONDS=4.72,FINAL_GAIN_DEADLINE_SECONDS=4.75):
            for phase in range(50):
                next_gain=phase/1000;final_sent=False;sent=[]
                for tick in range(4800):
                    now=tick/1000
                    final=trial.final_gain_due(now,0,None,final_sent)
                    if trial.gain_due(now,0,next_gain,None) or final:
                        sent.append(now);next_gain=now+.05
                        if final:final_sent=True
                self.assertTrue(final_sent)
                self.assertLessEqual(len(sent)+1,100)
                gaps=[b-a for a,b in zip(sent,sent[1:]+[4.8])]
                self.assertLess(max(gaps),.081)
                self.assertGreaterEqual(4.8-sent[-1],.079)


if __name__=='__main__':unittest.main()
