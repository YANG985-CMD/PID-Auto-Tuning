"""Prevent imbalance and missing actual contexts from producing false gains."""
import copy
import unittest
from speedloop_context_metrics import matched_metrics
from speedloop_lower_commission import PATTERN


def fixture():
    return [dict(slot=i, reference_phase=i % 9 // 3, level=label,
        response_mse_rpm2=(i % 9 + 1) * (1 if label == 0 else .81),
        peak_nominal_current_a=1 if label == 0 else 1.01,
        peak_speed_rpm=1000 if label == 0 else 999) for i, label in enumerate(PATTERN)]


class ContextMetricsTest(unittest.TestCase):
    def test_equal_context_weight_and_current_veto(self):
        result = matched_metrics(fixture(), (0, 1))
        self.assertAlmostEqual(result['scores'][1]['rmse_improvement_fraction'], .1)
        self.assertFalse(result['scores'][1]['descriptive_thresholds_met'])
        self.assertFalse(result['actor_admission'])

    def test_missing_context_rejected(self):
        rows = fixture()
        for row in rows:
            if row['slot'] % 9 == 0:
                row['level'] = 0
        with self.assertRaises(ValueError):
            matched_metrics(rows, (0, 1))

    def test_nonfinite_and_duplicate_rejected(self):
        rows = fixture()
        rows[0]['peak_speed_rpm'] = float('nan')
        with self.assertRaises(ValueError):
            matched_metrics(rows, (0, 1))
        rows = fixture()
        rows[1] = copy.deepcopy(rows[0])
        with self.assertRaises(ValueError):
            matched_metrics(rows, (0, 1))


if __name__ == '__main__':
    unittest.main()
