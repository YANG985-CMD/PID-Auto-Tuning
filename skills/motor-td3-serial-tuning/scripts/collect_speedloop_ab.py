"""Collect a bounded repeated baseline-vs-Actor-Kp comparison on the reviewed image.

The runner alternates baseline PI and the constrained MATLAB Actor Kp policy.
It never trains, flashes, retries a failed episode, or applies Ki exploration.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


ORDER = ("baseline", "actor_kp", "baseline", "actor_kp", "baseline", "actor_kp")
TRIAL_SECONDS = 3.0
COOLDOWN_SECONDS = 30.0


def run(a):
    output = Path(a.output).resolve()
    temp_root = Path("E:/simulink/_codex_tmp").resolve()
    if temp_root not in output.parents:
        raise ValueError("Repeated physical run output must be under the approved temporary root")
    output.mkdir(parents=True, exist_ok=True)
    script_root = Path(__file__).resolve().parent
    python = sys.executable
    records = []
    failure = None
    started = time.perf_counter()
    for index, policy in enumerate(ORDER, 1):
        if index > 1:
            time.sleep(COOLDOWN_SECONDS)
        round_dir = output / f"round-{index:02d}-{policy}"
        prepare_dir = round_dir / "prepare"
        trial_dir = round_dir / "trial"
        prepare_dir.mkdir(parents=True, exist_ok=True)
        prepare_cmd = [
            python, "-B", str(script_root / "speedloop_motion_prepare.py"),
            "--build", a.build, "--output", str(prepare_dir), "--nm", a.nm,
            "--energized-phase-inhibited-confirmed",
        ]
        prepare = subprocess.run(prepare_cmd, capture_output=True, text=True, check=False)
        (round_dir / "prepare.stdout.txt").write_text(prepare.stdout + prepare.stderr, encoding="utf-8")
        if prepare.returncode != 0:
            failure = f"prepare failed in round {index}"
            break
        token_file = prepare_dir / "boot-token.txt"
        trial_cmd = [
            python, "-B", str(script_root / "speedloop_motion_gain_trial.py"),
            "--build", a.build, "--output", str(trial_dir), "--nm", a.nm,
            "--boot-token-file", str(token_file),
            "--power-confirmed", "--authorized-no-thermal-trial",
            "--shadow-port", str(a.shadow_port), "--shadow-token-file", a.shadow_token_file,
        ]
        if policy == "actor_kp":
            trial_cmd.append("--apply-shadow-kp")
        trial = subprocess.run(trial_cmd, capture_output=True, text=True, check=False)
        (round_dir / "trial.stdout.txt").write_text(trial.stdout + trial.stderr, encoding="utf-8")
        summary_path = trial_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
            "passed": False, "error": "trial summary missing"
        }
        summary["comparison_policy"] = policy
        summary["round_index"] = index
        (trial_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        records.append(summary)
        if trial.returncode != 0 or not summary.get("passed"):
            failure = f"trial failed in round {index}"
            break
    elapsed = time.perf_counter() - started
    report = {
        "schema_version": 1,
        "source": "real_motor_repeated_ab",
        "utc": datetime.now(timezone.utc).isoformat(),
        "order": list(ORDER),
        "completed_rounds": len(records),
        "requested_rounds": len(ORDER),
        "reserved_motion_seconds": len(ORDER) * TRIAL_SECONDS,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "elapsed_host_seconds": elapsed,
        "hardware_accessed": True,
        "td3_training_performed": False,
        "actor_flash_written": False,
        "thermal_gate_modified": False,
        "failure": failure,
        "passed": failure is None and len(records) == len(ORDER) and
                  all(row.get("passed") for row in records),
        "rounds": [
            {
                "round_index": row.get("round_index"),
                "policy": row.get("comparison_policy"),
                "passed": row.get("passed"),
                "rmse_rpm": row.get("expected_post_start_window_rmse_rpm"),
                "peak_current_a": row.get("nominal_peak_current_a"),
                "peak_speed_rpm": row.get("peak_speed_rpm"),
                "actor_gain_commands": row.get("actor_gain_commands_sent", 0),
                "fault": row.get("final_irq_fault"),
                "stop_acknowledged": row.get("protocol_stop_acknowledged"),
            } for row in records
        ],
    }
    (output / "collection-summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "output", "nm", "shadow-token-file"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--shadow-port", type=int, required=True)
    a = parser.parse_args()
    raise SystemExit(0 if run(a)["passed"] else 1)
