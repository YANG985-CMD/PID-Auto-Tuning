"""Summarize alternating baseline/Actor-Kp trials with paired differences."""
import argparse
import json
from pathlib import Path
from statistics import mean, pstdev


METRICS = {
    "rmse_rpm": "expected_post_start_window_rmse_rpm",
    "peak_current_a": "nominal_peak_current_a",
    "peak_speed_rpm": "peak_speed_rpm",
}


def summarize(root, output):
    root = Path(root)
    collection = json.loads((root / "collection-summary.json").read_text(encoding="utf-8"))
    rows = []
    for round_dir in sorted(root.glob("round-*")):
        path = round_dir / "trial" / "summary.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            rows.append(row)
    groups = {}
    for row in rows:
        groups.setdefault(row.get("comparison_policy"), []).append(row)
    stats = {}
    for policy, policy_rows in groups.items():
        stats[policy] = {
            "n": len(policy_rows),
            "metrics": {
                label: {
                    "values": [float(row[key]) for row in policy_rows],
                    "mean": mean(float(row[key]) for row in policy_rows),
                    "std_population": pstdev(float(row[key]) for row in policy_rows),
                } for label, key in METRICS.items()
            },
            "faults": [row.get("final_irq_fault") for row in policy_rows],
            "stop_all_acknowledged": all(row.get("protocol_stop_acknowledged") for row in policy_rows),
        }
    baseline = groups.get("baseline", [])
    actor = groups.get("actor_kp", [])
    paired = []
    for b, a in zip(baseline, actor):
        paired.append({
            label: float(a[key]) - float(b[key]) for label, key in METRICS.items()
        })
    paired_stats = {
        label: {
            "values": [row[label] for row in paired],
            "mean_actor_minus_baseline": mean(row[label] for row in paired),
            "std_population": pstdev(row[label] for row in paired) if len(paired) > 1 else 0.0,
        } for label in METRICS
    }
    report = {
        "schema_version": 1,
        "source": "real_motor_repeated_ab",
        "hardware_accessed": False,
        "requested_rounds": collection.get("requested_rounds"),
        "completed_rounds": collection.get("completed_rounds"),
        "reserved_motion_seconds": collection.get("reserved_motion_seconds"),
        "statistics": stats,
        "paired_differences": paired_stats,
        "all_trials_passed": bool(rows) and all(row.get("passed") for row in rows),
        "performance_claim_allowed": False,
        "reason": "Three paired trials per policy; no unseen-condition validation and no independent current calibration",
        "deployment_recommendation": "hold_baseline_PI",
        "temperature_c": None,
        "current_conversion_independently_calibrated": False,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = summarize(args.root, args.output)
    raise SystemExit(0 if result["all_trials_passed"] else 1)
