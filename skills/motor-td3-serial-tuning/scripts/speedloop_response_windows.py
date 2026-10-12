"""Build disjoint held-gain response windows from audited physical records.

Same-gain lease refreshes can extend a response. A different applied gain,
unknown stage, missing sample, or episode boundary cannot be crossed.
This file has no serial, CAN, flash or device imports.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

BASE_KP, BASE_KI = .003389, .00144
SCALES = [1000, 1000, 1000, 1000, 3, 2, 24, BASE_KP, BASE_KI, 3000]
HOLDOUT = [5, 10, 15, 20, 23, 25, 29, 31, 35]
PROFILES = {"strict": (4, 60), "exploratory": (3, 40)}


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def state(r):
    return [r["speed_ref"], r["speed"], r["speed_ref"]-r["speed"], r["error_history"],
            r["integral_output"], r["current"], r["vbus"], r["kp"], r["ki"], r["elapsed_ms"]]


def temporal_mean(values, times):
    assert len(values) == len(times) and len(times) >= 2
    dt = [b-a for a, b in zip(times, times[1:])]
    assert min(dt) > 0
    return sum(.5*(a+b)*d for a, b, d in zip(values, values[1:], dt))/(times[-1]-times[0])


def build_trial(candidates, telemetry, min_samples=4, min_observed_ms=60):
    """Every source candidate belongs to one kept group or one rejection."""
    if not candidates:
        return [], []
    packets = {r["t_us"]: r for r in telemetry}
    assert len(packets) == len(telemetry), "Duplicate telemetry timestamp"
    assert all(b["seq"] == a["seq"]+1 and b["t_us"] > a["t_us"]
               for a, b in zip(telemetry, telemetry[1:])), "Broken telemetry order"
    assert all(r["fault"] == 0 for r in telemetry), "Faulted physical trial"
    for i, r in enumerate(candidates):
        assert r["stage_confirmed_from_raw_edges"] and not r["learner_eligible"]
        assert r["t_state_us"] <= r["t_apply_us"] < r["t_next_us"]
        assert state(packets[r["t_state_us"]]) == r["state"]
        assert state(packets[r["t_next_us"]]) == r["next_state"]
        if i:
            p = candidates[i-1]
            assert r["boot_id"] == p["boot_id"] and r["run_index"] == p["run_index"]
            assert r["t_state_us"] >= p["t_next_us"], "Overlapping source windows"
            if r["t_state_us"] == p["t_next_us"]:
                assert r["state"] == p["next_state"]
            assert r["command_seq"] > p["command_seq"]
    accepted, rejected = [], []
    i = 0
    while i < len(candidates):
        first, end = candidates[i], i
        holding = all(abs(a) < 1e-7 for a in first["action_normalized"])
        if holding:
            assert first["state"][7:9] == first["action_applied"], "Hold must already be read back"
        # An unchanged gain already exists at the source snapshot. Waiting
        # for a lease-refresh ACK would discard valid unchanged-gain data.
        effective = first["t_state_us"] if holding else first["t_apply_us"]
        while True:
            last = candidates[end]
            response = [r for r in telemetry if effective < r["t_us"] <= last["t_next_us"]]
            enough = (len(response) >= min_samples and
                      response[-1]["t_us"]-response[0]["t_us"] >= min_observed_ms*1000)
            if enough or end+1 == len(candidates):
                break
            following = candidates[end+1]
            if following["action_applied"] != first["action_applied"]:
                break
            gap_packets = [r for r in telemetry if last["t_next_us"] <= r["t_us"] <= following["t_state_us"]]
            if not all(r["enabled"] and [r["kp"],r["ki"]] == first["action_applied"] for r in gap_packets):
                break
            assert all(abs(a) < 1e-7 for a in following["action_normalized"]), \
                "Repeated target gain cannot relabel a nonzero physical action"
            end += 1
        members = candidates[i:end+1]
        if not enough:
            rejected.append({
                "run_index": first["run_index"], "boot_id": first["boot_id"],
                "source_command_seqs": [r["command_seq"] for r in members],
                "reason": "Too short before gain change or end of proven stage",
                "response_samples": len(response),
            })
            i = end+1
            continue
        assert all(r["enabled"] and r["fault"] == 0 and
                   [r["kp"], r["ki"]] == first["action_applied"] for r in response), \
            "Response includes another gain or stopped state"
        interval = [r for r in telemetry if first["t_state_us"] <= r["t_us"] <= last["t_next_us"]]
        gap = max(b["t_us"]-a["t_us"] for a, b in zip(interval, interval[1:]))/1000
        assert gap <= 40, "Telemetry gap"
        assert all(math.isfinite(v) for r in response for v in state(r)), "Nonfinite response"
        assert all(abs(r["speed"]) < 1800 and r["current"] < 2 and 18 <= r["vbus"] <= 30
                   for r in response), "Physical boundary"
        times = [r["t_us"] for r in response]
        err_mse = temporal_mean([(r["speed_ref"]-r["speed"])**2 for r in response], times)
        current_peak = max(abs(r["current"]) for r in response)
        speed_peak = max(abs(r["speed"]) for r in response)
        saturation = temporal_mean([float(abs(r["current"]) >= 1.98) for r in response], times)
        action = first["action_normalized"]
        reward = (-err_mse/1000000 - .12*(current_peak/2)**2
                  - .08*max(0, (speed_peak-1500)/300)**2
                  - .10*saturation - .005*sum(a*a for a in action))
        result = dict(first)
        # Historical rewards belong to the original short response only.
        result.pop("legacy_reward", None)
        result.pop("reweighted_reward", None)
        result.pop("reward_weights", None)
        result.update(
            schema_version=2, window_profile=f"held-gain-observed-{min_observed_ms}ms-{min_samples}samples-v1",
            t_next_us=last["t_next_us"], telemetry_seq_end=last["telemetry_seq_end"],
            next_state=last["next_state"], next_observation=last["next_observation"],
            reward=reward, reward_profile="time-weighted-current-speed-v3",
            response_rmse_rpm=math.sqrt(err_mse), response_peak_current_a=current_peak,
            response_peak_speed_rpm=speed_peak, response_saturation_ratio=saturation,
            response_sample_count=len(response), response_ms=(times[-1]-effective)/1000,
            t_effective_us=effective,
            action_effect_kind="already_confirmed_hold" if holding else "new_gain_applied",
            response_overshoot_rpm=max(0,max(r["speed"]-r["speed_ref"] for r in response)),
            observed_response_span_ms=(times[-1]-times[0])/1000,
            transition_duration_ms=(last["t_next_us"]-first["t_state_us"])/1000,
            max_frame_gap_ms=gap, source_command_seqs=[r["command_seq"] for r in members],
            response_telemetry_seqs=[r["seq"] for r in response],
            observed_applied_command_seqs=sorted(set(r.get("applied_seq",0) for r in response)),
            lease_refreshes_merged=len(members)-1, ordinary_live_learner_eligible=False,
            deployment_allowed=False, performance_claim_allowed=False,
            short_first_member_reward=first["reward"],
            discount_contract="gamma 0.99 per grouped decision; not a constant wall-time grid",
            discount_factor=.99,
            time_scaled_discount_diagnostic=.99**((last["t_next_us"]-first["t_state_us"])/100000),
            variable_duration_native_training_admitted=True,
            step=len(accepted),truncated=False,terminated=False,
        )
        assert all(r["action_applied"] == first["action_applied"] for r in members)
        accepted.append(result)
        i = end+1
    used = [seq for r in accepted+rejected for seq in r["source_command_seqs"]]
    assert sorted(used) == sorted(r["command_seq"] for r in candidates) and len(used) == len(set(used))
    response_used = [seq for r in accepted for seq in r["response_telemetry_seqs"]]
    assert len(response_used) == len(set(response_used)), "Overlapping response samples"
    if accepted:
        accepted[-1]["truncated"] = True
    return accepted, rejected


def physical_paths(base):
    paths = [base]+[base/"trials"/f"trial-{k:02d}" for k in range(1,17)]
    for batch in ("repeated-ab-20261012", "ki-coverage-20261012", "ki-coverage-2-20261012"):
        paths.extend(sorted((base/batch).glob("round-*")))
    assert len(paths) == 35
    return paths


def run(repository, output, extra_batches=(), profile="strict"):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in output.parents
    min_samples,min_span = PROFILES[profile]
    base = repository/"examples/speedloop-v5-real-20261012"
    old = lines(base/"offline-study-20261012/enhanced-td3/reweighted-transitions.jsonl")
    paths = physical_paths(base)
    candidates_by_run = {i: [r for r in old if r["run_index"] == i] for i in range(1,36)}
    holdout = list(HOLDOUT)
    for batch in extra_batches:
        batch = Path(batch).resolve()
        rounds = sorted(batch.glob("round-*"))
        assert len(rounds) == 6, "A completed six-round batch is required"
        holdout.append(len(paths)+6)  # Reserved before examining scores.
        for path in rounds:
            index = len(paths)+1
            first = lines(path/"telemetry.jsonl")[0]
            candidates = lines(path/"experience-candidates.jsonl")
            candidates = [r for r in candidates if r["stage_confirmed_from_raw_edges"]]
            for r in candidates:
                r.update(run_index=index,boot_id=first["boot_id"],validation_split=index in holdout)
            candidates_by_run[index] = candidates
            paths.append(path)
    accepted, rejected = [], []
    raw_hashes = {}; seen_boots=set(); seen_hashes=set()
    for index, path in enumerate(paths, 1):
        telemetry_path = path/"telemetry.jsonl"
        telemetry=lines(telemetry_path)
        boot=telemetry[0]["boot_id"]
        digest=hashlib.sha256(telemetry_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert boot not in seen_boots and digest not in seen_hashes, "Duplicate physical trial"
        seen_boots.add(boot);seen_hashes.add(digest)
        raw_hashes[path.relative_to(repository).as_posix()] = digest
        kept, refused = build_trial(candidates_by_run[index],telemetry,min_samples,min_span)
        accepted.extend(kept)
        rejected.extend(refused)
    train = [r for r in accepted if not r["validation_split"]]
    validation = [r for r in accepted if r["validation_split"]]
    assert {r["boot_id"] for r in train}.isdisjoint(r["boot_id"] for r in validation)
    report = {
        "schema_version": 1, "hardware_accessed": False, "source": "real_motor",
        "source_sessions": len(paths), "original_short_windows": sum(map(len,candidates_by_run.values())),
        "window_profile": profile,"exploratory_only": profile=="exploratory",
        "response_windows": len(accepted), "training_windows": len(train),
        "validation_windows": len(validation), "replay_warmup_required": 128,
        "replay_count_ready": len(train) >= 128 and bool(validation),
        "training_ready": len(train) >= 128 and bool(validation),
        "variable_duration_native_training_admitted": True,
        "discount_contract": "gamma 0.99 per grouped decision; state contains elapsed time",
        "minimum_observed_span_ms": min_span, "minimum_response_samples": min_samples,
        "response_sample_count_histogram": dict(Counter(r["response_sample_count"] for r in accepted)),
        "observed_span_ms_range": [min(r["observed_response_span_ms"] for r in accepted),
                                  max(r["observed_response_span_ms"] for r in accepted)],
        "transition_duration_ms_range": [min(r["transition_duration_ms"] for r in accepted),
                                        max(r["transition_duration_ms"] for r in accepted)],
        "lease_refreshes_merged": sum(r["lease_refreshes_merged"] for r in accepted),
        "ki_nonzero_delta_windows": sum(abs(r["action_normalized"][1]) > 1e-7 for r in accepted),
        "all_boot_ids": sorted(set(r["boot_id"] for seq in candidates_by_run.values() for r in seq)),
        "validation_run_indices": holdout, "raw_telemetry_sha256": raw_hashes,
        "td3_training_performed": False, "actor_deployed": False,
        "deployment_allowed": False, "performance_claim_allowed": False, "thermal_gate_modified": False,
        "limitations": ["This changes temporal action semantics; old-policy metrics are not transferable",
                        "Discount is per grouped decision, not per 100 ms of wall time",
                        "Counterfactual speed RMSE for a new Actor is unavailable"],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output/"response-windows.jsonl").write_bytes(
        b"".join((json.dumps(r, allow_nan=False)+"\n").encode() for r in accepted))
    report["dataset_sha256"]=hashlib.sha256((output/"response-windows.jsonl").read_bytes()).hexdigest()
    write(output/"window-summary.json", report)
    write(output/"rejected-groups.json", rejected)
    print(json.dumps(report))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--extra-batch", action="append", default=[])
    p.add_argument("--profile",choices=tuple(PROFILES),default="strict")
    args = p.parse_args()
    run(args.repository, args.output,args.extra_batch,args.profile)
