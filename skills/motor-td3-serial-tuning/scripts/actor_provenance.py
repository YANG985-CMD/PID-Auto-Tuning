#!/usr/bin/env python3
"""Validate the evidence attached to a TD3 Actor before hardware use.

The repository contains a mock Actor for MATLAB/C/PIL parity checks.  A model
with that provenance must never be presented as a policy trained from the
user's motor.  This module is deliberately small and dependency free so the
same gate can run in CI and in the export step.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_real_motor_provenance(model, dataset=None):
    """Return a list of blocking errors for a real-motor Actor candidate."""
    errors = []
    if model.get("simulation_only") is True:
        errors.append("model is marked simulation_only")
    data = model.get("training_data")
    if not isinstance(data, dict):
        return ["training_data provenance is missing"]
    if data.get("source") != "real_motor":
        errors.append("training_data.source must be real_motor")
    for key in ("dataset_sha256", "profile_id", "firmware_id", "protocol_id"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append("training_data.%s is missing" % key)
    for key in ("eligible_transitions", "episodes", "action_unique_count"):
        if not _positive_int(data.get(key)):
            errors.append("training_data.%s must be a positive integer" % key)
    if _positive_int(data.get("eligible_transitions")) and data["eligible_transitions"] < 128:
        errors.append("at least 128 eligible real-motor transitions are required")
    if _positive_int(data.get("episodes")) and data["episodes"] < 3:
        errors.append("at least 3 complete real-motor episodes are required")
    if _positive_int(data.get("action_unique_count")) and data["action_unique_count"] < 8:
        errors.append("real-motor actions do not cover the local gain domain")
    if dataset is not None:
        digest = hashlib.sha256(Path(dataset).read_bytes()).hexdigest()
        if data.get("dataset_sha256") != digest:
            errors.append("training_data.dataset_sha256 does not match the supplied dataset")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset")
    args = parser.parse_args()
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    errors = validate_real_motor_provenance(model, args.dataset)
    result = {"real_motor_provenance": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
