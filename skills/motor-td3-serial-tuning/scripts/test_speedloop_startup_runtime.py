import unittest
from types import SimpleNamespace
import speedloop_startup_review as review
import speedloop_duration_review as old
import speedloop_excitation_review as excitation

class Checks(unittest.TestCase):
    def test_scope_required_before_hardware(self):
        with self.assertRaises(ValueError):review.validate(SimpleNamespace(authorized_startup_review=False))

    def test_exact_profile_separation(self):
        self.assertNotEqual(review.IMAGE_SHA,old.IMAGE_SHA)
        self.assertNotEqual(review.IMAGE_SHA,excitation.IMAGE_SHA)
        self.assertEqual(review.OLD_SHA,excitation.IMAGE_SHA)
        self.assertEqual(review.OLD_BYTES,50456)

if __name__=='__main__':unittest.main()
