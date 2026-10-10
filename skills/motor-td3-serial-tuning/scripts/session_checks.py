#!/usr/bin/env python3
"""Check configuration and recorded experience. No serial or training imports."""

import argparse
import copy
import json
import math
import sys
from pathlib import Path


MODES = {"plan", "capture", "shadow", "train-live", "evaluate"}
REASONS = {"none", "safety_fault", "episode_limit", "operator_stop",
           "link_loss", "command_unconfirmed", "clock_reset"}
UNKNOWN_END = {"operator_stop", "link_loss", "command_unconfirmed", "clock_reset"}


def number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def decode_json(text):
    return json.loads(text, parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def load_json(path):
    return decode_json(Path(path).read_text(encoding="utf-8-sig"))


def nonfinite_paths(value, path="root"):
    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in nonfinite_paths(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for k, v in enumerate(value) for p in nonfinite_paths(v, f"{path}[{k}]")]
    return []


def check_profile(profile, live=False):
    errors, warnings = [], []
    if not isinstance(profile, dict):
        return ["Profile must be an object"], warnings
    errors.extend(f"Non-finite number: {p}" for p in nonfinite_paths(profile))
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        errors.append("schema_version must be integer 1")
    if not nonempty(profile.get("profile_id")):
        errors.append("profile_id is required")
    if profile.get("mode") not in MODES:
        errors.append("Unknown mode")
    sections = {}
    for name in ("device", "controller", "safety", "training"):
        value = profile.get(name)
        if not isinstance(value, dict):
            errors.append(f"{name} must be an object")
            value = {}
        sections[name] = value
    d, c, s, t = (sections[k] for k in ("device", "controller", "safety", "training"))
    if c.get("loop") != "speed-pi":
        errors.append("This contract only supports speed-pi")
    if t.get("algorithm") != "TD3" or t.get("task") != "adaptive-gains":
        errors.append("This contract requires TD3/adaptive-gains")
    fields = t.get("state_fields")
    if (not isinstance(fields, list) or not fields
            or not all(nonempty(f) for f in fields) or len(set(fields)) != len(fields)):
        errors.append("state_fields must be a nonempty list of unique field names")
    for key in ("kp_baseline", "ki_baseline"):
        if not number(c.get(key)) or c[key] < 0:
            errors.append(f"controller.{key} must be finite and nonnegative")

    if not live:
        warnings.append("Planning check only; this result does not permit hardware writes")
        return errors, warnings

    if profile.get("mode") == "plan":
        errors.append("Plan mode cannot be used for a hardware session")
    for key in ("port", "firmware_id", "protocol_id"):
        if not nonempty(d.get(key)):
            errors.append(f"device.{key} is required")
    rate_field = "bitrate" if d.get("transport") == "can" else "baudrate"
    if not integer(d.get(rate_field), 1):
        errors.append(f"device.{rate_field} must be a positive integer")
    required_verified = {
        "device": ("protocol_verified", "applied_parameter_feedback_verified",
                   "atomic_gain_update_verified", "single_parameter_owner_verified"),
        "controller": ("baseline_verified", "bumpless_update_verified"),
        "safety": ("safe_stop_verified", "independent_overcurrent_verified",
                   "firmware_link_loss_verified", "emergency_stop_verified",
                   "action_lease_verified", "host_stall_verified"),
        "training": ("state_units_verified", "fixed_policy_evaluation_verified"),
    }
    for section, keys in required_verified.items():
        for key in keys:
            if sections[section].get(key) is not True:
                errors.append(f"{section}.{key} must have verified evidence")
    for section, keys in {
        "controller": ("baseline_evidence",),
        "safety": ("limit_evidence", "thermal_evidence", "protection_evidence"),
        "training": ("normalization_id", "action_mapping_id"),
    }.items():
        for key in keys:
            if not nonempty(sections[section].get(key)):
                errors.append(f"{section}.{key} is required")
    if c.get("ki_convention") not in {"continuous-gain", "discrete-gain"}:
        errors.append("ki_convention must be continuous-gain or discrete-gain")
    for gain in ("kp", "ki"):
        lo, hi, baseline = (c.get(f"{gain}_{k}") for k in ("min", "max", "baseline"))
        step = c.get(f"max_{gain}_step")
        if not (number(lo) and number(hi) and 0 <= lo < hi):
            errors.append(f"Invalid {gain} bounds")
        elif not number(baseline) or not lo <= baseline <= hi:
            errors.append(f"{gain} baseline is outside its bounds")
        if not number(step) or step <= 0:
            errors.append(f"max_{gain}_step must be positive")
        elif number(lo) and number(hi) and step > hi - lo:
            errors.append(f"max_{gain}_step exceeds its full range")
    positive = (
        "current_limit_a", "speed_limit_rpm", "vbus_min_v", "vbus_max_v",
        "max_trial_seconds", "max_session_seconds", "max_frame_gap_ms",
        "max_apply_latency_ms", "decision_window_min_ms", "decision_window_max_ms",
        "action_lease_ms", "firmware_link_timeout_ms", "learner_progress_timeout_ms",
    )
    for key in positive:
        if not number(s.get(key)) or s[key] <= 0:
            errors.append(f"safety.{key} must be finite and positive")
    for lo, hi in (("vbus_min_v", "vbus_max_v"),
                   ("decision_window_min_ms", "decision_window_max_ms"),
                   ("max_trial_seconds", "max_session_seconds")):
        if number(s.get(lo)) and number(s.get(hi)):
            if s[lo] > s[hi] or (lo == "vbus_min_v" and s[lo] == s[hi]):
                errors.append(f"{lo} is inconsistent with {hi}")
    if not integer(s.get("max_commands_per_trial"), 1):
        errors.append("max_commands_per_trial must be a positive integer")
    if s.get("thermal_protection") not in {"measured", "verified_alternative"}:
        errors.append("A verified thermal protection method is required")
    if s.get("thermal_protection") == "measured" and not number(s.get("temperature_limit_c")):
        errors.append("Measured thermal protection needs a finite temperature limit")
    if all(number(s.get(k)) for k in ("action_lease_ms", "decision_window_max_ms", "max_apply_latency_ms")):
        if s["action_lease_ms"] <= s["decision_window_max_ms"] + s["max_apply_latency_ms"]:
            errors.append("Action lease must cover apply latency and the response window")
    if (number(s.get("decision_window_max_ms")) and number(s.get("max_trial_seconds"))
            and s["decision_window_max_ms"] >= 1000 * s["max_trial_seconds"]):
        errors.append("Response window must fit within the trial budget")
    if not number(t.get("fault_penalty")) or t["fault_penalty"] <= 0:
        errors.append("training.fault_penalty must be finite and positive")
    warnings.append("Complete configuration is not proof of protection, stability, or run authorization")
    return errors, warnings


def check_transition(row, profile):
    errors = []
    if not isinstance(row, dict):
        return ["Record must be an object"]
    errors.extend(f"Non-finite number: {p}" for p in nonfinite_paths(row))
    if type(row.get("schema_version")) is not int or row["schema_version"] != 1:
        errors.append("schema_version must be integer 1")
    for key in ("run_id", "episode_id", "policy_version"):
        if not nonempty(row.get(key)):
            errors.append(f"{key} is required")
    for key, expected in (("profile_id", profile["profile_id"]),
                          ("firmware_id", profile["device"]["firmware_id"]),
                          ("protocol_id", profile["device"]["protocol_id"])):
        if row.get(key) != expected:
            errors.append(f"{key} does not match the profile")
    if not integer(row.get("step")):
        errors.append("step must be a nonnegative integer")
    for key in ("terminated", "truncated", "learner_eligible", "safety_intervention"):
        if type(row.get(key)) is not bool:
            errors.append(f"{key} must be a boolean")
    if row.get("terminated") is True and row.get("truncated") is True:
        errors.append("terminated and truncated cannot both be true")
    reason = row.get("stop_reason")
    if reason not in REASONS:
        errors.append("Unknown stop_reason")
    if row.get("learner_eligible") is not True:
        return errors

    if row.get("safety_intervention") is not False:
        errors.append("Intervention record cannot enter this ordinary TD3 contract")
    if reason in UNKNOWN_END:
        errors.append("Unknown/stopped endpoint cannot enter the learner")
    if reason == "none" and (row.get("terminated") or row.get("truncated")):
        errors.append("An ended episode needs a stop reason")
    if reason == "episode_limit" and not (row.get("truncated") is True and row.get("terminated") is False):
        errors.append("Ordinary time limit must be truncated only")
    if reason == "safety_fault":
        if not (row.get("terminated") is True and row.get("truncated") is False):
            errors.append("Confirmed safety fault must be terminated only")
        if not number(row.get("reward")) or row["reward"] > -profile["training"]["fault_penalty"]:
            errors.append("Fault reward omits the configured penalty")
    if not number(row.get("reward")):
        errors.append("reward must be finite")
    fields = set(profile["training"]["state_fields"])
    for key in ("state", "next_state"):
        state = row.get(key)
        if not isinstance(state, dict) or set(state) != fields or not all(number(v) for v in state.values()):
            errors.append(f"{key} must match the profile fields with finite numeric values")
    for key in ("action_proposed", "action_applied"):
        action = row.get(key)
        if (not isinstance(action, dict) or set(action) != {"kp", "ki"}
                or not all(number(v) for v in action.values())):
            errors.append(f"{key} must contain finite kp and ki")
    applied = row.get("action_applied", {})
    if isinstance(applied, dict):
        for gain in ("kp", "ki"):
            if number(applied.get(gain)):
                c = profile["controller"]
                if not c[f"{gain}_min"] <= applied[gain] <= c[f"{gain}_max"]:
                    errors.append(f"Applied {gain} is outside the validated range")
    if row.get("action_proposed") != row.get("action_applied"):
        errors.append("Proposed/applied mismatch needs an explicit intervention contract")
    for key in ("command_seq", "applied_command_seq", "next_applied_command_seq",
                "t_state_us", "t_apply_us", "t_next_us", "telemetry_seq_start", "telemetry_seq_end"):
        if not integer(row.get(key)):
            errors.append(f"{key} must be a nonnegative integer")
    if row.get("command_seq") != row.get("applied_command_seq"):
        errors.append("Command application was not confirmed")
    if reason != "safety_fault" and row.get("applied_command_seq") != row.get("next_applied_command_seq"):
        errors.append("Another command changed parameters during the response window")
    s = profile["safety"]
    if all(integer(row.get(k)) for k in ("t_state_us", "t_apply_us", "t_next_us")):
        t0, ta, t1 = (row[k] for k in ("t_state_us", "t_apply_us", "t_next_us"))
        if not t0 <= ta < t1:
            errors.append("Device timestamps are not causally ordered")
        if (ta - t0) / 1000 > s["max_apply_latency_ms"]:
            errors.append("Apply latency exceeds the profile")
        window = (t1 - ta) / 1000
        minimum = 0 if reason == "safety_fault" else s["decision_window_min_ms"]
        if not (window > 0 and minimum <= window <= s["decision_window_max_ms"]):
            errors.append("Response window exceeds the profile")
    if all(integer(row.get(k)) for k in ("telemetry_seq_start", "telemetry_seq_end")):
        if row["telemetry_seq_end"] <= row["telemetry_seq_start"]:
            errors.append("Telemetry sequence must increase")
    gap = row.get("max_frame_gap_ms")
    if not number(gap) or not 0 <= gap <= s["max_frame_gap_ms"]:
        errors.append("Telemetry frame gap is invalid or excessive")
    return errors


def audit_rows(rows, profile):
    errors, warnings = check_profile(profile, live=True)
    report = {"records": 0, "eligible": 0, "excluded": 0,
              "errors": errors, "warnings": warnings, "trainable": False}
    if errors:
        return report
    previous = None
    closed = set()
    for line_number, row in enumerate(rows, 1):
        report["records"] += 1
        row_errors = check_transition(row, profile)
        if not row_errors:
            key = (row["run_id"], row["episode_id"])
            if previous and key == (previous["run_id"], previous["episode_id"]):
                if previous["terminated"] or previous["truncated"]:
                    row_errors.append("A terminated episode was continued")
                if row["step"] != previous["step"] + 1:
                    row_errors.append("Steps are not contiguous")
                if row["learner_eligible"] and not previous["learner_eligible"]:
                    row_errors.append("Learning cannot resume across an excluded interval; start a verified new episode")
                if row["learner_eligible"] and previous["learner_eligible"]:
                    if row["state"] != previous["next_state"]:
                        row_errors.append("State is not the previous next_state")
                    if row["t_state_us"] != previous["t_next_us"]:
                        row_errors.append("Transition device times do not join")
                    if row["command_seq"] <= previous["command_seq"]:
                        row_errors.append("Command sequence was reused or reversed")
                    for gain in ("kp", "ki"):
                        delta = abs(row["action_applied"][gain] - previous["action_applied"][gain])
                        if delta > profile["controller"][f"max_{gain}_step"] + 1e-12:
                            row_errors.append(f"Applied {gain} change exceeds the profile")
            else:
                if row["step"] != 0 or key in closed:
                    row_errors.append("New episode must start at step 0 and cannot reopen")
                if previous:
                    closed.add((previous["run_id"], previous["episode_id"]))
                    if not (previous["terminated"] or previous["truncated"]):
                        row_errors.append("Previous episode has no recorded end")
                if row["learner_eligible"]:
                    for gain in ("kp", "ki"):
                        if abs(row["action_applied"][gain] - profile["controller"][f"{gain}_baseline"]) > profile["controller"][f"max_{gain}_step"] + 1e-12:
                            row_errors.append(f"First {gain} action exceeds the baseline step limit")
            previous = row
        if row_errors:
            report["errors"].extend(f"record {line_number}: {e}" for e in row_errors)
        elif row["learner_eligible"]:
            report["eligible"] += 1
        else:
            report["excluded"] += 1
    if report["records"] == 0:
        report["errors"].append("Log has no records")
    report["trainable"] = not report["errors"] and report["eligible"] > 0
    if previous and not (previous["terminated"] or previous["truncated"]):
        report["warnings"].append("Final episode is incomplete; do not synthesize a terminal transition")
    return report


def self_test():
    template = Path(__file__).resolve().parents[1] / "assets" / "session-profile.example.json"
    p = load_json(template)
    assert not check_profile(p)[0]
    assert check_profile(p, live=True)[0]
    p["mode"] = "train-live"
    d, c, s, t = (p[k] for k in ("device", "controller", "safety", "training"))
    for section in (d, c, s, t):
        for key in section:
            if key.endswith("verified"):
                section[key] = True
    d.update(port="MOCK_ONLY", baudrate=115200, firmware_id="mock-fw", protocol_id="mock-v1")
    c.update(kp_min=.003, kp_max=.004, ki_min=.001, ki_max=.002,
             max_kp_step=.0001, max_ki_step=.0001,
             ki_convention="continuous-gain", baseline_evidence="mock-only")
    s.update(current_limit_a=1, speed_limit_rpm=1000, vbus_min_v=20, vbus_max_v=28,
             thermal_protection="verified_alternative", max_trial_seconds=1,
             max_session_seconds=10, max_commands_per_trial=10, max_frame_gap_ms=5,
             max_apply_latency_ms=2, decision_window_min_ms=10, decision_window_max_ms=20,
             action_lease_ms=50, firmware_link_timeout_ms=30, learner_progress_timeout_ms=50,
             limit_evidence="mock-only", thermal_evidence="mock-only", protection_evidence="mock-only")
    t.update(normalization_id="mock-scales", action_mapping_id="mock-gains", fault_penalty=100)
    assert not check_profile(p, live=True)[0]
    fixed_window = copy.deepcopy(p)
    fixed_window["safety"].update(decision_window_min_ms=20, max_session_seconds=1)
    assert not check_profile(fixed_window, live=True)[0]
    state = {field: 0.0 for field in t["state_fields"]}
    row = dict(schema_version=1, run_id="mock-run", episode_id="mock-episode", step=0,
               profile_id=p["profile_id"], firmware_id=d["firmware_id"], protocol_id=d["protocol_id"],
               policy_version="mock-policy", state=state, next_state=state.copy(),
               action_proposed={"kp": c["kp_baseline"], "ki": c["ki_baseline"]},
               action_applied={"kp": c["kp_baseline"], "ki": c["ki_baseline"]},
               command_seq=1, applied_command_seq=1, next_applied_command_seq=1,
               t_state_us=0, t_apply_us=1000, t_next_us=21000,
               telemetry_seq_start=1, telemetry_seq_end=21, max_frame_gap_ms=1.0,
               reward=-1.0, terminated=False, truncated=False, stop_reason="none",
               safety_intervention=False, learner_eligible=True)
    assert audit_rows([row], p)["trainable"]
    mutations = [
        ("reward", float("nan")), ("t_apply_us", 22000),
        ("applied_command_seq", 2), ("next_applied_command_seq", 2),
        ("max_frame_gap_ms", 50), ("learner_eligible", "true"),
        ("stop_reason", "link_loss"), ("stop_reason", "safety_fault"),
        ("state", {"speed": 0}), ("safety_intervention", True),
        ("action_applied", {"kp": .01, "ki": .00144}),
        ("action_proposed", {"kp": .0034, "ki": .00144}),
    ]
    for key, value in mutations:
        bad = copy.deepcopy(row)
        bad[key] = value
        assert audit_rows([bad], p)["errors"], key
    second = copy.deepcopy(row)
    second.update(step=1, command_seq=2, applied_command_seq=2, next_applied_command_seq=2,
                  t_state_us=21000, t_apply_us=22000, t_next_us=42000,
                  telemetry_seq_start=21, telemetry_seq_end=42,
                  truncated=True, stop_reason="episode_limit")
    assert audit_rows([row, second], p)["trainable"]
    bad = copy.deepcopy(second)
    bad["state"]["speed"] = 1
    assert audit_rows([row, bad], p)["errors"]
    bad = copy.deepcopy(second)
    bad["step"] = 3
    assert audit_rows([row, bad], p)["errors"]
    assert audit_rows([second, row], p)["errors"]
    fault = copy.deepcopy(row)
    fault.update(terminated=True, stop_reason="safety_fault", reward=-101, t_next_us=5000)
    assert audit_rows([fault], p)["trainable"]
    assert audit_rows([fault, second], p)["errors"]
    excluded = copy.deepcopy(row)
    excluded.update(learner_eligible=False, terminated=True, stop_reason="link_loss")
    result = audit_rows([excluded], p)
    assert not result["errors"] and result["excluded"] == 1 and not result["trainable"]
    interval = copy.deepcopy(row)
    interval.update(learner_eligible=False, safety_intervention=True)
    assert audit_rows([interval, second], p)["errors"]
    bad = copy.deepcopy(row)
    bad.update(action_applied={"kp": .0037, "ki": .00144},
               action_proposed={"kp": .0037, "ki": .00144})
    assert audit_rows([bad], p)["errors"]
    changed = copy.deepcopy(second)
    changed.update(action_applied={"kp": .0037, "ki": .00144},
                   action_proposed={"kp": .0037, "ki": .00144})
    assert audit_rows([row, changed], p)["errors"]
    for bad_json in ('{"x": NaN}', '{"x": 1e999}', '{"x": 1, "x": 2}'):
        try:
            decoded = decode_json(bad_json)
        except ValueError:
            continue
        assert nonfinite_paths(decoded), bad_json
    print(json.dumps({"self_test": "passed", "hardware_access": False, "training_executed": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    profile_parser = commands.add_parser("check-profile")
    profile_parser.add_argument("profile")
    profile_parser.add_argument("--live", action="store_true")
    audit_parser = commands.add_parser("audit-transitions")
    audit_parser.add_argument("log")
    audit_parser.add_argument("--profile", required=True)
    commands.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return 0
        p = load_json(args.profile)
        if args.command == "check-profile":
            errors, warnings = check_profile(p, args.live)
            result = {"errors": errors, "warnings": warnings,
                      "configuration_complete": args.live and not errors,
                      "hardware_authorized": False}
        else:
            with Path(args.log).open(encoding="utf-8-sig") as stream:
                rows = (decode_json(line) for line in stream if line.strip())
                result = audit_rows(rows, p)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 2 if result["errors"] else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc), "hardware_access": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
