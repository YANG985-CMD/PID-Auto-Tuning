"""Apply the offline candidate admission rule without deploying anything."""
import argparse
import json
from pathlib import Path


def select(training_path, repeated_path, output):
    training = json.loads(Path(training_path).read_text(encoding="utf-8"))
    repeated = json.loads(Path(repeated_path).read_text(encoding="utf-8"))
    reasons = []
    if training.get("action_mask") != [1, 0]:
        reasons.append("Ki action mask is not fixed")
    if training.get("ki_exploration_performed"):
        reasons.append("Ki exploration was observed")
    if not all(row.get("action_bounds_passed") and row.get("gain_bounds_passed")
               for row in training.get("seed_reports", [])):
        reasons.append("At least one seed failed action or gain bounds")
    if not training.get("offline_performance_verified"):
        reasons.append("Offline performance is not plant validation")
    if not training.get("seed_kp_action_direction_consistent", False):
        reasons.append("Training seeds disagree on Kp action direction")
    baseline = repeated["statistics"]["baseline"]["metrics"]
    actor = repeated["statistics"]["actor_kp"]["metrics"]
    rmse_improvement = (
        baseline["rmse_rpm"]["mean"] - actor["rmse_rpm"]["mean"]
    ) / baseline["rmse_rpm"]["mean"]
    current_change = actor["peak_current_a"]["mean"] - baseline["peak_current_a"]["mean"]
    peak_speed_change = actor["peak_speed_rpm"]["mean"] - baseline["peak_speed_rpm"]["mean"]
    if rmse_improvement < .05:
        reasons.append("Repeated real-motor RMSE improvement is below 5 percent")
    if current_change > 0:
        reasons.append("Repeated real-motor peak nominal current increased")
    if peak_speed_change > 0:
        reasons.append("Repeated real-motor peak speed increased")
    if not repeated.get("all_trials_passed") or not all(
            fault == 0 for policy in ("baseline", "actor_kp")
            for fault in repeated["statistics"][policy]["faults"]):
        reasons.append("Repeated trial safety evidence is incomplete")
    report = {
        "schema_version": 1,
        "source": "td3-candidate-admission",
        "candidate_status": "rejected",
        "selected_seed": None,
        "deployment_allowed": False,
        "performance_claim_allowed": False,
        "hold_baseline_pi": True,
        "training_summary": str(Path(training_path)),
        "repeated_comparison": str(Path(repeated_path)),
        "rmse_improvement_fraction_actor_minus_baseline": rmse_improvement,
        "peak_nominal_current_change_a_actor_minus_baseline": current_change,
        "peak_speed_change_rpm_actor_minus_baseline": peak_speed_change,
        "reasons": reasons,
        "next_required_evidence": [
            "Collect Ki action coverage or keep Ki permanently fixed",
            "Validate a retrained candidate on unseen real-motor conditions",
            "Independently calibrate current conversion before ordinary deployment admission",
        ],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", required=True)
    parser.add_argument("--repeated", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = select(args.training, args.repeated, args.output)
    raise SystemExit(0 if result["candidate_status"] == "rejected" else 1)
