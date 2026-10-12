"""Compare two completed, same-budget SpeedLoop trials without overstating evidence."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(baseline_path, candidate_path, output):
    baseline, candidate = read(baseline_path), read(candidate_path)
    for label, row in (("baseline", baseline), ("candidate", candidate)):
        if not row.get("passed"):
            raise ValueError(label + " trial did not pass")
        if row.get("firmware_id") != candidate.get("firmware_id"):
            raise ValueError("Firmware identity mismatch")
        if row.get("speed_ref_rpm") != candidate.get("speed_ref_rpm"):
            raise ValueError("Speed reference mismatch")
        if row.get("maximum_motion_seconds") != candidate.get("maximum_motion_seconds"):
            raise ValueError("Motion budget mismatch")
        if row.get("final_irq_fault") or row.get("final_tx_fault"):
            raise ValueError(label + " trial has a final fault")
    metrics = (
        "expected_post_start_window_rmse_rpm",
        "nominal_peak_current_a",
        "peak_speed_rpm",
        "active_snapshots",
        "actual_gain_commands",
    )
    comparison = {
        "schema_version": 1,
        "source": "same-budget-real-motor-trial-comparison",
        "hardware_accessed": False,
        "baseline_summary": str(Path(baseline_path)),
        "candidate_summary": str(Path(candidate_path)),
        "baseline_policy": baseline.get("shadow_mode", "baseline_PI"),
        "candidate_policy": candidate.get("shadow_mode", "candidate"),
        "candidate_actor_applied": candidate.get("actor_applied", False),
        "candidate_actor_gain_commands": candidate.get("actor_gain_commands_sent", 0),
        "ki_baseline": 0.00144,
        "single_trial_per_policy": True,
        "performance_claim_allowed": False,
        "reason": "One trial per policy; no repeated or unseen-condition validation",
        "metrics": {
            key: {
                "baseline": baseline.get(key),
                "candidate": candidate.get(key),
                "delta_candidate_minus_baseline": (
                    candidate.get(key) - baseline.get(key)
                    if isinstance(candidate.get(key), (int, float)) and
                       isinstance(baseline.get(key), (int, float)) else None),
            } for key in metrics
        },
        "safety": {
            "baseline_fault": baseline.get("final_irq_fault", 0),
            "candidate_fault": candidate.get("final_irq_fault", 0),
            "baseline_stop_acknowledged": baseline.get("protocol_stop_acknowledged", False),
            "candidate_stop_acknowledged": candidate.get("protocol_stop_acknowledged", False),
            "baseline_outputs_off": baseline.get("core_halted_after_physical_shutdown", False),
            "candidate_outputs_off": candidate.get("core_halted_after_physical_shutdown", False),
        },
        "temperature_c": None,
        "current_conversion_independently_calibrated": False,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(comparison, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(comparison, allow_nan=False))
    return comparison


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    compare(args.baseline, args.candidate, args.output)
