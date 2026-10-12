"""No hardware access: exact policy binding and fail-closed physical gates."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from select_td3_candidate import select


class CandidateSelectionChecks(unittest.TestCase):
    def setUp(self):
        self.training = {
            "action_mask": [1, 0], "seed_kp_action_direction_consistent": True,
            "seed_reports": [{"seed": 7, "checkpoint_sha256": "a" * 64,
                              "action_bounds_passed": True, "gain_bounds_passed": True}],
        }
        def group(rmse, current, speed):
            return {"n": 3, "faults": [0, 0, 0],
                    **{key: True for key in ("stop_all_acknowledged", "outputs_all_closed",
                         "cores_all_halted", "can_all_released", "actions_all_in_bounds")},
                    "metrics": {k: {"mean": v, "values": [v] * 3} for k, v in
                                zip(("rmse_rpm", "peak_current_a", "peak_speed_rpm"), (rmse, current, speed))}}
        self.evidence = {
            "candidate_checkpoint_sha256": "a" * 64, "policy_action_mask": [1, 0],
            "all_trials_passed": True, "comparable_protocol": True,
            "statistics": {"baseline": group(100, 1, 1000), "actor_kp": group(90, 1, 1000)},
        }

    def run_gate(self, training=None, evidence=None):
        with tempfile.TemporaryDirectory(dir="E:/simulink/_codex_tmp") as folder:
            root = Path(folder)
            (root / "train.json").write_text(json.dumps(training or self.training))
            (root / "eval.json").write_text(json.dumps(evidence or self.evidence))
            return select(root / "train.json", root / "eval.json", root / "out.json", quiet=True)

    def test_matching_pass_still_keeps_deployment_closed(self):
        result = self.run_gate()
        self.assertEqual(result["candidate_status"], "repeat_evaluation_passed")
        self.assertFalse(result["deployment_allowed"])
        self.assertFalse(result["performance_claim_allowed"])

    def test_old_checkpoint_metrics_are_not_assigned_to_new_actor(self):
        self.evidence["candidate_checkpoint_sha256"] = "b" * 64
        result = self.run_gate()
        self.assertEqual(result["candidate_status"], "not_evaluated")
        self.assertIsNone(result["candidates"][0]["physical_metrics"])

    def test_same_checkpoint_different_mask_not_matched(self):
        self.evidence["policy_action_mask"] = [1, 1]
        self.assertEqual(self.run_gate()["candidate_status"], "not_evaluated")

    def test_regression_rejected(self):
        self.evidence["statistics"]["actor_kp"]["metrics"]["rmse_rpm"] = {"mean": 110, "values": [110]*3}
        self.assertEqual(self.run_gate()["candidate_status"], "rejected")

    def test_nan_fault_and_missing_shutdown_each_rejected(self):
        for kind in ("nan", "fault", "shutdown"):
            e = copy.deepcopy(self.evidence)
            if kind == "nan":
                e["statistics"]["actor_kp"]["metrics"]["rmse_rpm"] = {"mean": float("nan"), "values": [90]*3}
            elif kind == "fault":
                e["statistics"]["actor_kp"]["faults"][0] = 8
            else:
                del e["statistics"]["actor_kp"]["outputs_all_closed"]
            self.assertEqual(self.run_gate(evidence=e)["candidate_status"], "rejected")

    def test_empty_seeds_rejected(self):
        self.training["seed_reports"] = []
        self.assertEqual(self.run_gate()["candidate_status"], "rejected")

    def test_short_batch_rejected(self):
        self.evidence["statistics"]["actor_kp"]["n"] = 1
        self.assertEqual(self.run_gate()["candidate_status"], "rejected")

    def test_ki_without_training_direction_coverage_rejected(self):
        self.training["action_mask"] = [1, 1]
        self.training["ki_exploration_performed"] = True
        self.training["training_action_coverage"] = {"positive": [10, 0], "negative": [10, 2]}
        self.assertEqual(self.run_gate()["candidate_status"], "rejected")

    def test_seed_inconsistency_is_not_a_physical_regression_measurement(self):
        self.training["seed_kp_action_direction_consistent"] = False
        self.evidence["candidate_checkpoint_sha256"] = "b" * 64
        result = self.run_gate()
        self.assertEqual(result["candidate_status"], "rejected")
        self.assertIsNone(result["candidates"][0]["physical_metrics"])


if __name__ == "__main__":
    unittest.main()
