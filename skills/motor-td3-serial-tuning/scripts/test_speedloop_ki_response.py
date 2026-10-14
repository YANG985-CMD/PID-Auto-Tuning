"""No hardware tests: finite Ki schedule, context coverage and early rejection."""
import unittest
from types import SimpleNamespace
from speedloop_ki_response import KI_LEVELS, PATTERN, KiProbe, validate
from speedloop_motion_gain_trial import f32


class KiResponseTest(unittest.TestCase):
    def test_all_points_per_cycle_and_reference(self):
        for cycle in range(5):
            self.assertEqual(set(PATTERN[cycle * 3:cycle * 3 + 3]), {0, 1, 2})
        for phase in range(3):
            self.assertEqual(sorted(PATTERN[phase::3].count(level) for level in range(3)), [1, 2, 2])

    def test_all_steps_fixed_kp_and_restoration(self):
        probe = KiProbe()
        for elapsed in range(0, 24001, 20):
            kp, ki = probe.planned(elapsed)
            self.assertEqual(kp, f32(.003389))
            self.assertIn(ki, KI_LEVELS)
            if elapsed < 3850 or elapsed >= 22000:
                self.assertEqual(ki, f32(.00144))
        self.assertEqual(len(probe.decisions), 15)

    def test_missed_schedule_and_unauthorized_rejected(self):
        probe = KiProbe()
        probe.planned(3900)
        with self.assertRaises(RuntimeError):
            probe.planned(6400)
        with self.assertRaises(ValueError):
            validate(SimpleNamespace(authorized_ki_response=False))


if __name__ == '__main__':
    unittest.main()
