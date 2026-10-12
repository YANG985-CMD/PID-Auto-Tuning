"""Publish a fixed real-data offline study; no device or MATLAB access."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics

from select_td3_candidate import select

CONFIGS = ("legacy-td3", "enhanced-td3", "legacy-td3-bc", "enhanced-td3-bc")
BASE_KP, BASE_KI = .003389, .00144


def canonical(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def output_closed(summary):
    s = summary["final_board_state"]
    return (not s["tim1_bdtr"] & 0x8000 and not s["tim1_ccer"] & 0x555
            and s["gpioa_moder"] & 0x3f0000 == 0x150000
            and s["gpiob_moder"] & 0xfc000000 == 0x54000000
            and not s["gpioa_odr"] & 0x700 and not s["gpiob_odr"] & 0xe000)


def bind_old_policy(base):
    summaries = [load(p / "summary.json") for p in sorted((base / "repeated-ab-20261012").glob("round-*"))]
    actors = [s for s in summaries if s.get("actor_applied") is True]
    hashes = {s["shadow"]["checkpoint_sha256"] for s in actors}
    assert len(summaries) == 6 and len(actors) == 3 and len(hashes) == 1
    groups = {}
    for policy in ("baseline", "actor_kp"):
        selected = [s for s in summaries if s["comparison_policy"] == policy]
        assert len(selected) == 3
        metrics = {}
        for name, field in (("rmse_rpm", "expected_post_start_window_rmse_rpm"),
                            ("peak_current_a", "nominal_peak_current_a"),
                            ("peak_speed_rpm", "peak_speed_rpm")):
            values = [s[field] for s in selected]
            metrics[name] = {"values": values, "mean": statistics.mean(values)}
        groups[policy] = {
            "n": len(selected), "metrics": metrics,
            "faults": [max(s["final_irq_fault"], s["final_tx_fault"]) for s in selected],
            "stop_all_acknowledged": all(s["protocol_stop_acknowledged"] for s in selected),
            "outputs_all_closed": all(output_closed(s) for s in selected),
            "cores_all_halted": all(s["core_halted_after_physical_shutdown"] for s in selected),
            "can_all_released": all(s["can_released_after_shutdown"] for s in selected),
            "actions_all_in_bounds": all(
                .0013556 <= kp <= .0054224 and .00072 <= ki <= .00216
                for s in selected for kp, ki in s["gain_pairs"]),
        }
    fixed_baseline = all(all(abs(kp - BASE_KP) < 1e-9 and abs(ki - BASE_KI) < 1e-9
                             for kp, ki in s["gain_pairs"])
                         for s in summaries if s["comparison_policy"] == "baseline")
    return {
        "schema_version": 2, "source": "real_motor_repeated_ab_hash_bound",
        "candidate_checkpoint_sha256": hashes.pop(), "policy_action_mask": [1, 0],
        "comparison_policies": [s["comparison_policy"] for s in summaries],
        "comparable_protocol": fixed_baseline and all(
            (s["speed_ref_rpm"], s["maximum_motion_seconds"], s["host_stop_seconds"], s["gain_interval_ms"])
            == (1000, 3, 2.8, 50) for s in summaries),
        "statistics": groups, "all_trials_passed": all(s["passed"] for s in summaries),
        "performance_claim_allowed": False, "deployment_allowed": False,
        "limitations": ["Expected post-start 2.2s window is not proven steady state",
                        "Nominal current only; no independent current calibration",
                        "This evidence applies only to the bound Kp-only checkpoint"],
    }


def run(repository, study):
    repository, study = Path(repository).resolve(), Path(study).resolve()
    temp_root = Path("E:/simulink/_codex_tmp").resolve()
    assert temp_root in study.parents
    base = repository / "examples/speedloop-v5-real-20261012"
    dest = base / "offline-study-20261012"
    dest.mkdir(parents=True, exist_ok=True)
    study_report = load(study / "study-summary.json")
    bound = bind_old_policy(base)
    write(dest / "bound-old-policy-comparison.json", bound)
    published_reports = []
    comparison_rows = []
    for name in CONFIGS:
        src, dst = study / name, dest / name
        dst.mkdir(parents=True, exist_ok=True)
        report = load(src / "reweighted-training-summary.json")
        for file in src.glob("*.csv"):
            (dst / file.name).write_bytes(canonical(file))
        for file in src.glob("networks-seed-*.json"):
            (dst / file.name).write_bytes(canonical(file))
        transitions = canonical(src / "reweighted-transitions.jsonl")
        (dst / "reweighted-transitions.jsonl").write_bytes(transitions)
        report["training_output_dataset_sha256"] = report["dataset_sha256"]
        report["dataset_sha256"] = sha(transitions)
        report["publication_line_endings"] = "UTF-8 LF; original source byte hashes retained separately"
        report["candidate_files"] = []
        for seed in report["seed_reports"]:
            filename = f'reweighted-candidate-seed-{seed["seed"]}.mat'
            final = repository / "models/offline-study-20261012" / name / filename
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / filename, final)
            assert sha(final.read_bytes()) == seed["checkpoint_sha256"]
            report["candidate_files"].append(final.relative_to(repository).as_posix())
            after = seed["validation_after"]
            comparison_rows.append({
                "config": name, "seed": seed["seed"], "gradient_steps": seed["training_steps_total"],
                "kp_action_mean": after["action_mean"][0], "ki_action_mean": after["action_mean"][1],
                "kp_behavior_mse": after["behavior_action_mse"][0], "ki_behavior_mse": after["behavior_action_mse"][1],
                "kp_zero_action_mse": after["zero_action_mse"][0], "ki_zero_action_mse": after["zero_action_mse"][1],
                "critic_disagreement": after["critic_disagreement_mean"],
                "critic1_residual_rmse": after["online_bellman_residual_rmse"][0],
                "critic2_residual_rmse": after["online_bellman_residual_rmse"][1],
                "actor_weight_change_l2": seed["actor_weight_change_l2"],
                "checkpoint_sha256": seed["checkpoint_sha256"],
                "physical_performance_verified": False,
            })
        write(dst / "reweighted-training-summary.json", report)
        gate = select(dst / "reweighted-training-summary.json", dest / "bound-old-policy-comparison.json",
                      dst / "candidate-selection.json", quiet=True)
        gate["training_summary"] = f"{name}/reweighted-training-summary.json"
        gate["repeated_comparison"] = "bound-old-policy-comparison.json"
        write(dst / "candidate-selection.json", gate)
        published_reports.append(report)
    study_report["reports"] = published_reports
    write(dest / "study-summary.json", study_report)
    test_path = study.parent / "matlab-tests.json"
    if test_path.exists():
        write(dest / "matlab-tests.json", load(test_path))
    runtime_test_path = study.parent / "runtime-tests/runtime-tests.json"
    if runtime_test_path.exists():
        write(dest / "runtime-tests.json", load(runtime_test_path))
    python_test_path = study.parent / "python-offline-tests.json"
    python_tests = load(python_test_path)
    runtime_tests, matlab_tests = load(runtime_test_path), load(test_path)
    assert python_tests["passed"] and runtime_tests["passed"]
    assert matlab_tests["passed"] == matlab_tests["tests"]
    write(dest / "python-offline-tests.json", python_tests)
    write(dest / "verification-summary.json", {
        "python_protocol_runtime_tests": runtime_tests["tests_run"],
        "python_admission_gain_schedule_shadow_tests": python_tests["tests"],
        "matlab_offline_tests": matlab_tests["tests"],
        "actor_json_weight_roundtrips": len(comparison_rows),
        "critic_json_weight_roundtrips": 2 * len(comparison_rows),
        "hardware_accessed_by_checks": False,
        "final_actor_c_generated": False,
        "deployment_allowed": False,
    })
    with (dest / "ablation.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(comparison_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(comparison_rows)
    transitions = rows(dest / "enhanced-td3/reweighted-transitions.jsonl")
    assert len(transitions) == 311
    paths = [base] + [base / "trials" / f"trial-{k:02d}" for k in range(1, 17)]
    for batch in ("repeated-ab-20261012", "ki-coverage-20261012", "ki-coverage-2-20261012"):
        paths.extend(sorted((base / batch).glob("round-*")))
    assert len(paths) == 35
    original_hashes, published_hashes = {}, {}
    peak_before_training, annotations = [], []
    for index, path in enumerate(paths, 1):
        summary = load(path / "summary.json")
        telemetry = rows(path / "telemetry.jsonl")
        active = [r for r in telemetry if r["enabled"]]
        first_source = min(r["t_state_us"] for r in transitions if r["run_index"] == index)
        peak = max(active, key=lambda r: abs(r["speed"]))
        peak_before_training.append(peak["t_us"] < first_source)
        kp_probe = max(kp for kp, _ in summary["gain_pairs"]) - min(kp for kp, _ in summary["gain_pairs"]) > 1e-9
        if path.parent.name.startswith("ki-coverage") and summary.get("comparison_policy") == "baseline":
            annotations.append({
                "path": path.relative_to(repository).as_posix(),
                "original_label": "baseline",
                "corrected_actual_behavior": "kp_probe" if kp_probe else "fixed_baseline",
                "fixed_PI_performance_comparison_eligible": not kp_probe,
                "raw_record_rewritten": False,
            })
        for filename in ("telemetry.jsonl", "commands.jsonl", "hall-edges.json", "summary.json"):
            file = path / filename
            relative = file.relative_to(repository).as_posix()
            original_hashes[relative] = sha(file.read_bytes())
            published_hashes[relative] = sha(canonical(file))
    actions = [r["action_normalized"] for r in transitions]
    counts = {
        key: [sum(predicate(a[c]) for a in actions) for c in range(2)]
        for key, predicate in (("positive", lambda v: v > 1e-7),
                               ("negative", lambda v: v < -1e-7),
                               ("zero", lambda v: abs(v) <= 1e-7))
    }
    intervention_onsets = sum(abs(r["action_normalized"][1]) > 1e-7 and abs(r["state"][8] - BASE_KI) < 1e-9 for r in transitions)
    coverage = {
        "schema_version": 1, "hardware_accessed": False, "source": "real_motor",
        "physical_sessions": 35, "causal_windows": len(transitions),
        "training_windows": published_reports[0]["training_experiences"],
        "validation_windows": published_reports[0]["validation_experiences"],
        "validation_run_indices": published_reports[0]["validation_run_indices"],
        "unique_boot_count": len(set(r["boot_id"] for r in transitions)),
        "action_direction_counts_kp_ki": counts,
        "ki_nonzero_delta_windows": sum(abs(a[1]) > 1e-7 for a in actions),
        "ki_intervention_onsets": intervention_onsets,
        "ki_return_to_baseline_windows": sum(abs(r["action_normalized"][1]) > 1e-7 and abs(r["action_applied"][1] - BASE_KI) < 1e-9 for r in transitions),
        "ki_offset_held_windows": sum(abs(r["action_applied"][1] - BASE_KI) > 1e-9 for r in transitions),
        "response_sample_count_histogram": dict(Counter(r["response_sample_count"] for r in transitions)),
        "response_ms_range": [min(r["response_ms"] for r in transitions), max(r["response_ms"] for r in transitions)],
        "source_elapsed_ms_range": [min(r["state"][9] for r in transitions), max(r["state"][9] for r in transitions)],
        "reference_speed_rpm_values": sorted(set(r["state"][0] for r in transitions)),
        "near_speed_penalty_nonzero_windows": sum(r["response_peak_speed_rpm"] > 1500 for r in transitions),
        "saturation_penalty_nonzero_windows": sum(r["response_saturation_ratio"] > 0 for r in transitions),
        "full_trial_peak_before_first_training_source_sessions": sum(peak_before_training),
        "baseline_label_corrections": annotations,
        "gate_issue_fixed": "Old-policy A/B metrics cannot score a different checkpoint/mask",
        "limitations": ["Only 1000 rpm, no unseen speed/load coverage",
                        "Changing holding duration does not add intervention directions",
                        "Short consecutive windows are correlated; holdout is by episode",
                        "Logged outcomes cannot give counterfactual RMSE for a new Actor"],
        "deployment_allowed": False,
    }
    write(dest / "coverage-analysis.json", coverage)
    write(dest / "source-byte-hashes.json", {"files": original_hashes,
          "convention": "Original local input bytes, before Git line-ending normalization"})
    # Keep original bytes in the archived raw files. This manifest hashes the
    # exact LF content published by Git, independently of checkout settings.
    for file in dest.rglob("*"):
        if file.is_file() and file.name != "published-sha256.json":
            published_hashes[file.relative_to(repository).as_posix()] = sha(canonical(file))
    write(dest / "published-sha256.json", {"files": published_hashes,
          "convention": "Published UTF-8 LF Git blobs; legacy byte manifests are superseded for publication"})
    print(json.dumps({"coverage": coverage, "gradient_steps": study_report["total_gradient_steps"],
                      "candidates": len(comparison_rows), "published_files_hashed": len(published_hashes)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--study", required=True)
    args = parser.parse_args()
    run(args.repository, args.study)
