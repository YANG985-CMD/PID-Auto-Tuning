"""Audit fixed-Actor suggestions against real telemetry without claiming plant response.

This is a counterfactual action audit. It never opens CAN/UART, never writes gains,
and never converts Actor suggestions into measured performance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

LOWER = (.0013556, .00072)
UPPER = (.0054224, .00216)
STEP = (.00027112, .000144)
BASELINE = (.003389, .00144)


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(telemetry_path, predictions_path, output):
    output = Path(output).resolve()
    telemetry = load_jsonl(telemetry_path)
    predictions = load_jsonl(predictions_path)
    assert telemetry and predictions
    by_seq = {int(row["seq"]): row for row in telemetry}
    accepted = [row for row in predictions if row.get("accepted") and "result" in row]
    aligned = []
    rejected = []
    for row in predictions:
        result = row.get("result")
        if not result:
            rejected.append(row)
            continue
        seq = int(row["telemetry_seq"])
        source = by_seq.get(seq)
        if source is None or row["boot_id"] != source["boot_id"] or row["t_us"] != source["t_us"]:
            rejected.append(dict(row, rejection="source_not_aligned"))
            continue
        gains = result["original_two_head_gains"]
        if (len(gains) != 2 or not all(math.isfinite(float(x)) for x in gains) or
                any(not lo <= float(gains[i]) <= hi for i, (lo, hi) in enumerate(zip(LOWER, UPPER)))):
            rejected.append(dict(row, rejection="gain_out_of_bounds"))
            continue
        source_gains = (float(source["kp"]), float(source["ki"]))
        for i in range(2):
            if abs(float(gains[i]) - source_gains[i]) > STEP[i] + 2e-7:
                rejected.append(dict(row, rejection="step_out_of_bounds"))
                break
        else:
            aligned.append((source, result, row))
    kp_delta = [float(result["kp"]) - float(source["kp"]) for source, result, _ in aligned]
    ki_delta = [float(result["ki"]) - float(source["ki"]) for source, result, _ in aligned]
    unmasked_ki_delta = [float(result["original_two_head_gains"][1]) - float(source["ki"])
                         for source, result, _ in aligned]
    active = [row for row in telemetry if row.get("enabled")]
    speed_errors = [float(row["speed_ref"]) - float(row["speed"]) for row in active]
    baseline_metrics = {
        "active_snapshots": len(active),
        "speed_rmse_rpm": (sum(x*x for x in speed_errors) / len(speed_errors)) ** 0.5 if speed_errors else None,
        "peak_abs_speed_rpm": max((abs(float(row["speed"])) for row in active), default=None),
        "peak_nominal_current_a": max((float(row["current"]) for row in active), default=None),
    }
    report = {
        "schema_version": 1,
        "source": "real_motor_shadow_audit",
        "hardware_accessed": False,
        "motor_motion_started": False,
        "actor_applied": False,
        "counterfactual_performance_evaluated": False,
        "reason": "Actor proposals were not applied to the plant",
        "telemetry_rows": len(telemetry),
        "prediction_rows": len(predictions),
        "aligned_accepted_predictions": len(aligned),
        "rejected_predictions": len(rejected),
        "actor_policy_version": accepted[0]["result"]["policy_version"] if accepted else None,
        "checkpoint_sha256": accepted[0]["result"]["checkpoint_sha256"] if accepted else None,
        "ki_masked_all_rows": bool(aligned) and all(
            result.get("ki_masked") and abs(float(result["ki"]) - BASELINE[1]) < 1e-7
            for _, result, _ in aligned),
        "baseline_metrics": baseline_metrics,
        "baseline_metrics_include_startup_transient": True,
        "ki_fixed_baseline": bool(aligned) and all(
            result.get("ki_masked") and abs(float(result["ki"]) - BASELINE[1]) < 1e-7
            for _, result, _ in aligned),
        "actor_kp_delta": {
            "min": min(kp_delta) if kp_delta else None,
            "max": max(kp_delta) if kp_delta else None,
            "mean": sum(kp_delta) / len(kp_delta) if kp_delta else None,
        },
        "actor_ki_delta": {
            "min": min(ki_delta) if ki_delta else None,
            "max": max(ki_delta) if ki_delta else None,
            "mean": sum(ki_delta) / len(ki_delta) if ki_delta else None,
        },
        "unmasked_actor_ki_delta": {
            "min": min(unmasked_ki_delta) if unmasked_ki_delta else None,
            "max": max(unmasked_ki_delta) if unmasked_ki_delta else None,
            "mean": sum(unmasked_ki_delta) / len(unmasked_ki_delta) if unmasked_ki_delta else None,
        },
        "source_telemetry_sha256": hashlib.sha256(Path(telemetry_path).read_bytes()).hexdigest(),
        "source_predictions_sha256": hashlib.sha256(Path(predictions_path).read_bytes()).hexdigest(),
        "passed": bool(aligned and not rejected and
                       bool(aligned) and all(result.get("shadow_only") and
                                             result.get("hardware_writeback") is False
                                             for _, result, _ in aligned)),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "actor-shadow-audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telemetry", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(args.telemetry, args.predictions, args.output)["passed"] else 1)
