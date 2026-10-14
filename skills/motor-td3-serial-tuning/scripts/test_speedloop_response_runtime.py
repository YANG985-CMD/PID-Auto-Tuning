"""Offline action masks, heartbeat schedule and exact-image entry checks."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_response_review as review
import speedloop_motion_gain_trial as trial


class Checks(unittest.TestCase):
    def test_new_scope_required(self):
        with self.assertRaises(ValueError):review.validate(SimpleNamespace(authorized_response_review=False))

    def test_actor_ki_and_unreviewed_modes_blocked(self):
        for bad in ({'apply_shadow_kp':True},{'ki_probe_sign':1},{'gain_mode':'ki_probe'},
                    {'shadow_port':55000}):
            with self.assertRaises(ValueError):review.validate_action(SimpleNamespace(**bad))
        with self.assertRaises(ValueError):review.planned_gains(5500,1,'kp_probe')
        for mode in ('baseline','kp_probe'):
            for t in (0,2200,4999,5000,5999,6000,7720):
                kp,ki=review.planned_gains(t,0,mode)
                self.assertEqual(ki,trial.f32(.00144))
                self.assertEqual(kp,trial.f32(.00352456 if mode=='kp_probe' and 5000<=t<6000 else .003389))

    def test_deadlines_budget_and_lease(self):
        with review.overrides(trial,STOP_SECONDS=7.8,GAIN_CUTOFF_SECONDS=7.7,
            FINAL_GAIN_SECONDS=7.72,FINAL_GAIN_DEADLINE_SECONDS=7.75):
            for phase in range(50):
                next_gain=phase/1000;sent=[];final=False
                for tick in range(7800):
                    now=tick/1000
                    final_due=trial.final_gain_due(now,0,None,final)
                    if trial.gain_due(now,0,next_gain,None) or final_due:
                        sent.append(now);next_gain=now+.05
                        if final_due:final=True
                self.assertTrue(final)
                self.assertLessEqual(len(sent)+1,160)
                self.assertLess(max(b-a for a,b in zip(sent,sent[1:]+[7.8])),.081)

    def test_overrides_restored_after_fault(self):
        old=(trial.MAX_MOTION_SECONDS,trial.HALL_TRACE_CAPACITY,trial.planned_gains)
        with self.assertRaises(RuntimeError):
            with review.overrides(trial,MAX_MOTION_SECONDS=8,HALL_TRACE_CAPACITY=768,
                                  planned_gains=review.planned_gains):
                raise RuntimeError('injected')
        self.assertEqual(old,(trial.MAX_MOTION_SECONDS,trial.HALL_TRACE_CAPACITY,trial.planned_gains))


if __name__=='__main__':unittest.main()
