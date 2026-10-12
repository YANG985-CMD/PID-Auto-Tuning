"""Admission-gate checks; no MATLAB, CAN, UART or hardware access."""
import json
from pathlib import Path
import tempfile
import unittest

from select_td3_candidate import select


class CandidateSelectionChecks(unittest.TestCase):
    def test_rejects_missing_plant_validation_and_regression(self):
        with tempfile.TemporaryDirectory(dir="E:/simulink/_codex_tmp") as folder:
            root = Path(folder)
            training = {
                "action_mask": [1, 0],
                "ki_exploration_performed": False,
                "offline_performance_verified": False,
                "seed_kp_action_direction_consistent": False,
                "seed_reports": [{"action_bounds_passed": True, "gain_bounds_passed": True}],
            }
            repeated = {
                "all_trials_passed": True,
                "statistics": {
                    "baseline": {"metrics": {
                        "rmse_rpm": {"mean": 100.0},
                        "peak_current_a": {"mean": 1.0},
                        "peak_speed_rpm": {"mean": 1000.0},
                    }, "faults": [0]},
                    "actor_kp": {"metrics": {
                        "rmse_rpm": {"mean": 110.0},
                        "peak_current_a": {"mean": 1.1},
                        "peak_speed_rpm": {"mean": 1010.0},
                    }, "faults": [0]},
                },
            }
            train_path = root / "training.json"
            repeated_path = root / "repeated.json"
            output = root / "selection.json"
            train_path.write_text(json.dumps(training), encoding="utf-8")
            repeated_path.write_text(json.dumps(repeated), encoding="utf-8")
            result = select(train_path, repeated_path, output)
            self.assertEqual(result["candidate_status"], "rejected")
            self.assertFalse(result["deployment_allowed"])
            self.assertTrue(output.exists())
            self.assertGreaterEqual(len(result["reasons"]), 4)


if __name__ == "__main__":
    unittest.main()
