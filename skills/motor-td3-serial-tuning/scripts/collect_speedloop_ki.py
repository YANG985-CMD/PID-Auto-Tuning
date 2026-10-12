"""Collect a bounded Ki-coverage batch with Kp held at baseline.

This is data collection only. It does not train, deploy an Actor, flash, or
alter the ordinary safety gates. Any failed round aborts the batch.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ORDER = ("baseline", "ki_plus", "baseline", "ki_minus", "ki_plus", "ki_minus")
SIGN = {"baseline": 0, "ki_plus": 1, "ki_minus": -1}
TRIAL_SECONDS = 3.0
COOLDOWN_SECONDS = 30.0


def run(args):
    output = Path(args.output).resolve()
    temp_root = Path("E:/simulink/_codex_tmp").resolve()
    if temp_root not in output.parents:
        raise ValueError("Use the approved temporary root")
    output.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    records = []
    failure = None
    for index, policy in enumerate(ORDER, 1):
        if index > 1:
            time.sleep(COOLDOWN_SECONDS)
        round_dir = output / f"round-{index:02d}-{policy}"
        prepare_dir, trial_dir = round_dir / "prepare", round_dir / "trial"
        prepare_dir.mkdir(parents=True, exist_ok=True)
        prepare = subprocess.run([
            sys.executable, "-B", str(scripts / "speedloop_motion_prepare.py"),
            "--build", args.build, "--output", str(prepare_dir), "--nm", args.nm,
            "--energized-phase-inhibited-confirmed",
        ], capture_output=True, text=True, check=False)
        (round_dir / "prepare.stdout.txt").write_text(
            prepare.stdout + prepare.stderr, encoding="utf-8")
        if prepare.returncode:
            failure = f"prepare failed in round {index}"
            break
        trial = subprocess.run([
            sys.executable, "-B", str(scripts / "speedloop_motion_gain_trial.py"),
            "--build", args.build, "--output", str(trial_dir), "--nm", args.nm,
            "--boot-token-file", str(prepare_dir / "boot-token.txt"),
            "--power-confirmed", "--authorized-no-thermal-trial",
            "--ki-probe-sign", str(SIGN[policy]),
            "--gain-mode", "baseline" if policy == "baseline" else "ki_probe",
        ], capture_output=True, text=True, check=False)
        (round_dir / "trial.stdout.txt").write_text(
            trial.stdout + trial.stderr, encoding="utf-8")
        summary_path = trial_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
            "passed": False, "error": "trial summary missing"}
        summary["comparison_policy"] = policy
        summary["round_index"] = index
        summary["ki_probe_sign"] = SIGN[policy]
        summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        records.append(summary)
        if trial.returncode or not summary.get("passed"):
            failure = f"trial failed in round {index}"
            break
    report = {
        "schema_version": 1,
        "source": "real_motor_ki_coverage",
        "utc": datetime.now(timezone.utc).isoformat(),
        "order": list(ORDER),
        "completed_rounds": len(records),
        "requested_rounds": len(ORDER),
        "reserved_motion_seconds": len(ORDER) * TRIAL_SECONDS,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "hardware_accessed": True,
        "td3_training_performed": False,
        "actor_flash_written": False,
        "thermal_gate_modified": False,
        "failure": failure,
        "passed": failure is None and len(records) == len(ORDER) and
                  all(row.get("passed") for row in records),
        "rounds": [{
            "round_index": row.get("round_index"),
            "policy": row.get("comparison_policy"),
            "ki_probe_sign": row.get("ki_probe_sign"),
            "passed": row.get("passed"),
            "rmse_rpm": row.get("expected_post_start_window_rmse_rpm"),
            "peak_current_a": row.get("nominal_peak_current_a"),
            "peak_speed_rpm": row.get("peak_speed_rpm"),
            "fault": row.get("final_irq_fault"),
            "stop_acknowledged": row.get("protocol_stop_acknowledged"),
        } for row in records],
    }
    (output / "collection-summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "output", "nm"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args)["passed"] else 1)
