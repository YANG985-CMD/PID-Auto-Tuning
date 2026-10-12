"""Bind physical performance evidence to the exact Actor checkpoint and action mask."""
import argparse
import json
import math
import re
from pathlib import Path


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_hash(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _physical_score(evidence):
    """Missing, short, faulty or incomparable experiments fail closed."""
    reasons = []
    stats = evidence.get("statistics", {})
    metric_names = ("rmse_rpm", "peak_current_a", "peak_speed_rpm")
    for policy in ("baseline", "actor_kp"):
        group = stats.get(policy, {})
        n = group.get("n", 0)
        if not isinstance(n, int) or isinstance(n, bool) or n < 3:
            reasons.append("Need at least three trials per policy")
            continue
        faults = group.get("faults", [])
        if len(faults) != n or any(type(f) is not int or f != 0 for f in faults):
            reasons.append("Incomplete or nonzero fault evidence")
        for field in ("stop_all_acknowledged", "outputs_all_closed",
                      "cores_all_halted", "can_all_released", "actions_all_in_bounds"):
            if group.get(field) is not True:
                reasons.append("Missing shutdown or action evidence: " + field)
        for name in metric_names:
            m = group.get("metrics", {}).get(name, {})
            values = m.get("values", [])
            if (len(values) != n or not all(_finite(v) and v >= 0 for v in values)
                    or not _finite(m.get("mean"))
                    or abs(sum(values) / n - m["mean"]) > 1e-6):
                reasons.append("Invalid metric values: " + name)
    if evidence.get("all_trials_passed") is not True or evidence.get("comparable_protocol") is not True:
        reasons.append("Physical protocol or stop evidence incomplete")
    if reasons:
        return None, sorted(set(reasons))
    b, a = stats["baseline"]["metrics"], stats["actor_kp"]["metrics"]
    if b["rmse_rpm"]["mean"] <= 0:
        return None, ["Baseline RMSE must be positive"]
    metrics = {
        "rmse_improvement_fraction": (b["rmse_rpm"]["mean"] - a["rmse_rpm"]["mean"]) / b["rmse_rpm"]["mean"],
        "peak_nominal_current_change_a": a["peak_current_a"]["mean"] - b["peak_current_a"]["mean"],
        "peak_speed_change_rpm": a["peak_speed_rpm"]["mean"] - b["peak_speed_rpm"]["mean"],
    }
    if metrics["rmse_improvement_fraction"] < .05:
        reasons.append("Repeated real-motor RMSE improvement below 5 percent")
    if metrics["peak_nominal_current_change_a"] > 0:
        reasons.append("Peak nominal current increased")
    if metrics["peak_speed_change_rpm"] > 0:
        reasons.append("Peak speed increased")
    return metrics, reasons


def select(training_path, repeated_path, output, *, quiet=False):
    training = json.loads(Path(training_path).read_text(encoding="utf-8"))
    repeated = json.loads(Path(repeated_path).read_text(encoding="utf-8"))
    mask = training.get("action_mask")
    global_reasons = []
    seeds = training.get("seed_reports", [])
    if not seeds:
        global_reasons.append("No candidate seed reports")
    if mask not in ([1, 0], [1, 1]):
        global_reasons.append("Unsupported action mask")
    if mask == [1, 1]:
        coverage = training.get("training_action_coverage", {})
        pos, neg = coverage.get("positive", []), coverage.get("negative", [])
        if (not training.get("ki_exploration_performed") or len(pos) != 2 or len(neg) != 2
                or not _finite(pos[1]) or not _finite(neg[1]) or min(pos[1], neg[1]) <= 0):
            global_reasons.append("Training split lacks both real Ki action directions")
    direction_ok = training.get("seed_kp_action_direction_consistent") is True
    evaluations = repeated.get("evaluations", [repeated])
    candidates = []
    for seed in seeds:
        sha = seed.get("checkpoint_sha256")
        reasons = list(global_reasons)
        for field in ("action_bounds_passed", "gain_bounds_passed"):
            if seed.get(field) is not True:
                reasons.append("Candidate failed " + field)
        if not _valid_hash(sha):
            reasons.append("Missing exact checkpoint SHA-256")
        matched = [e for e in evaluations if _valid_hash(sha)
                   and e.get("candidate_checkpoint_sha256") == sha
                   and e.get("policy_action_mask") == mask]
        metrics = None
        if len(matched) > 1:
            reasons.append("Ambiguous physical evaluation binding")
        elif len(matched) == 1 and not reasons:
            metrics, physical_reasons = _physical_score(matched[0])
            reasons.extend(physical_reasons)
        elif not matched:
            reasons.append("No physical evaluation for this checkpoint and action mask")
        if not direction_ok:
            reasons.append("Seed direction inconsistency; experimental screening remains closed")
        if not reasons:
            status = "repeat_evaluation_passed"
        elif metrics is None and not matched and direction_ok and not global_reasons and _valid_hash(sha) and all(
                seed.get(k) is True for k in ("action_bounds_passed", "gain_bounds_passed")):
            status = "not_evaluated"
        else:
            status = "rejected"
        candidates.append({
            "seed": seed.get("seed"), "checkpoint_sha256": sha,
            "candidate_status": status, "physical_metrics": metrics,
            "physical_evaluation_matched": len(matched) == 1,
            "deployment_allowed": False, "performance_claim_allowed": False,
            "reasons": reasons,
        })
    passed = [c for c in candidates if c["candidate_status"] == "repeat_evaluation_passed"]
    report = {
        "schema_version": 2, "source": "td3-candidate-admission",
        "candidate_status": "repeat_evaluation_passed" if passed else (
            "not_evaluated" if candidates and all(c["candidate_status"] == "not_evaluated" for c in candidates) else "rejected"),
        "selected_seed": passed[0]["seed"] if passed else None,
        "candidates": candidates, "reasons": global_reasons,
        "deployment_allowed": False, "performance_claim_allowed": False,
        "hold_baseline_pi": True, "thermal_gate_modified": False,
        "training_summary": str(Path(training_path)),
        "repeated_comparison": str(Path(repeated_path)),
        "next_required_evidence": [
            "Exact-policy repeated physical RMSE improvement >=5 percent, no current or speed increase",
            "Untrained-condition evaluation with the same fixed policy",
            "Existing thermal gate and independent current calibration for ordinary deployment",
        ],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if not quiet:
        print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--training", required=True)
    p.add_argument("--repeated", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    select(args.training, args.repeated, args.output)
