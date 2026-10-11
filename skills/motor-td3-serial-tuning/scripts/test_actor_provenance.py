#!/usr/bin/env python3
"""Tests for the real-motor Actor provenance gate; no hardware access."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from actor_provenance import validate_real_motor_provenance


ROOT = Path(__file__).resolve().parents[3]


class ActorProvenanceTests(unittest.TestCase):
    def test_mock_actor_is_rejected(self):
        model = json.loads((ROOT / "examples/mock-validation/actor.json").read_text())
        errors = validate_real_motor_provenance(model)
        self.assertIn("training_data provenance is missing", errors)

    def test_real_dataset_identity_and_minimum_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "transitions.jsonl"
            dataset.write_text('{"schema_version":1}\n', encoding="utf-8")
            model = {
                "simulation_only": False,
                "training_data": {
                    "source": "real_motor",
                    "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                    "profile_id": "g431-speedloop-td3-v1",
                    "firmware_id": "g431-speedloop-td3-v1",
                    "protocol_id": "motor-td3-can-v1",
                    "eligible_transitions": 256,
                    "episodes": 4,
                    "action_unique_count": 16,
                },
            }
            self.assertEqual(validate_real_motor_provenance(model, dataset), [])

    def test_bad_dataset_hash_and_coverage_are_rejected(self):
        model = {
            "simulation_only": False,
            "training_data": {
                "source": "real_motor",
                "dataset_sha256": "0" * 64,
                "profile_id": "p",
                "firmware_id": "f",
                "protocol_id": "q",
                "eligible_transitions": 16,
                "episodes": 1,
                "action_unique_count": 1,
            },
        }
        errors = validate_real_motor_provenance(model)
        self.assertTrue(any("128" in error for error in errors))
        self.assertTrue(any("3 complete" in error for error in errors))
        self.assertTrue(any("gain domain" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
