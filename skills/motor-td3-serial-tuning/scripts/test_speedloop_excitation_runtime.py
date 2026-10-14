"""Exact-image and excitation contracts, no hardware imports or movement."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_excitation_review as review
import speedloop_response_review as old
import collect_speedloop_excitation as collector


class Checks(unittest.TestCase):
    def test_unreviewed_actor_and_scope_rejected(self):
        with self.assertRaises(ValueError):review.validate(SimpleNamespace(authorized_excitation_review=False))
        for bad in ({'apply_shadow_kp':True},{'ki_probe_sign':1},{'gain_mode':'ki_probe'},{'shadow_port':55000}):
            with self.assertRaises(ValueError):review.validate_action(SimpleNamespace(**bad))

    def test_reference_boundaries(self):
        for t,ref in ((0,1000),(3997,1000),(4003,1100),(5197,1100),(5203,900),(6403,1000),(7800,1000)):
            self.assertTrue(review.reference_matches(t,ref))
            for bad in (0,800,1200):self.assertFalse(review.reference_matches(t,bad))
        self.assertFalse(review.reference_matches(4003,1000))
        self.assertTrue(review.reference_matches(4001,1000))

    def test_fixed_ki_and_windows(self):
        for mode in ('baseline','kp_probe'):
            for t in (0,3899,3900,4000,5200,6400,6999,7000,7720):
                kp,ki=review.planned_gains(t,0,mode)
                self.assertEqual(ki,review.trial.f32(.00144))
                self.assertEqual(kp,review.trial.f32(.00352456 if mode=='kp_probe' and 3900<=t<7000 else .003389))
        self.assertNotEqual(review.IMAGE_SHA,old.IMAGE_SHA)
        self.assertEqual(review.OLD_SHA,old.IMAGE_SHA)

    def test_collector_does_not_relax_old_entry(self):
        original=collector.collector.REVIEW_SCRIPT
        with patch.object(collector.collector,'run',return_value={'passed':False}) as run:
            collector.run(SimpleNamespace())
            run.assert_called_once()
        self.assertEqual(collector.collector.REVIEW_SCRIPT,original)


if __name__=='__main__':unittest.main()
