"""Explain fixed-replay sensitivity using observed data; no motor access."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def mean(values):
    return statistics.mean(values)


def integral(values,times):
    return sum((a+b)*.5*(tb-ta)/1e6 for a,b,ta,tb in
               zip(values,values[1:],times,times[1:]))


def analyze(task,batch):
    task,batch=Path(task),Path(batch)
    rows=lines(task/"strict/response-windows.jsonl")
    training=[r for r in rows if not r["validation_split"]]
    ki_changes=sum(abs(r["action_normalized"][1])>1e-7 for r in training)
    known_sources={(r["boot_id"],r["t_state_us"]) for r in training}
    without_successor=sum((r["boot_id"],r["t_next_us"]) not in known_sources for r in training)
    with (task/"noise-study/ablation.csv").open(encoding="utf-8") as f:
        results=list(csv.DictReader(f))
    grouped={}
    for name in sorted({r["config"] for r in results}):
        selected=[r for r in results if r["config"]==name]
        means=[float(r["kp_action_mean"]) for r in selected]
        grouped[name]={
            "critic_disagreement_mean":mean(float(r["critic_disagreement"]) for r in selected),
            "critic1_residual_mean":mean(float(r["critic1_residual_rmse"]) for r in selected),
            "critic2_residual_mean":mean(float(r["critic2_residual_rmse"]) for r in selected),
            "kp_mean_actions":means,"kp_seed_spread":max(means)-min(means),
            "kp_direction_consistent":all(x>=0 for x in means) or all(x<=0 for x in means),
            "kp_mean_delta_as_baseline_fraction":[x*.00027112/.003389 for x in means],
        }
    default=grouped["default-noise-bc2p5"];small=grouped["small-noise-bc2p5"]
    per_trial=[]
    for folder in sorted(batch.glob("round-*")):
        s=json.loads((folder/"summary.json").read_text(encoding="utf-8"))
        a=json.loads((folder/"analysis.json").read_text(encoding="utf-8"))
        raw=lines(folder/"telemetry.jsonl")
        active=[r for r in raw if r["enabled"] and 2200<=r["elapsed_ms"]<=2720]
        times=[r["t_us"] for r in active]
        terms=[(r["ki"]-.00144)*(r["speed_ref"]-r["speed"]) for r in active]
        per_trial.append(dict(round=folder.name,policy=s["comparison_policy"],
            stage_proven_rmse_rpm=a["raw_stage_window_rmse_rpm"],
            nominal_peak_current_a=s["nominal_peak_current_a"],peak_speed_rpm=s["peak_speed_rpm"],
            signed_extra_integrator_term_replay=integral(terms,times),
            absolute_extra_integrator_term_replay=integral([abs(x) for x in terms],times),
            replay_term_is_counterfactual_response=False))
    baseline=[r["stage_proven_rmse_rpm"] for r in per_trial if r["policy"]=="baseline"]
    report=dict(schema_version=1,hardware_accessed=False,
        training_windows=len(training),ki_nonzero_delta_training_windows=ki_changes,
        ki_zero_delta_training_fraction=mean(abs(r["action_normalized"][1])<=1e-7 for r in training),
        default_target_noise_std=math.sqrt(.2),small_target_noise_std=.05,
        default_noise_probability_outside_ki_logged_global_interval_at_zero_actor=math.erfc(.25/math.sqrt(.4)),
        small_noise_probability_outside_ki_logged_global_interval_at_zero_actor=0,
        noise_probability_assumptions="Actor centered at zero; logged Ki range +/-0.25, Gaussian clipped at +/-0.5 or +/-0.1. This is not conditional action support.",
        configs=grouped,
        small_noise_critic_disagreement_reduction_fraction=1-small["critic_disagreement_mean"]/default["critic_disagreement_mean"],
        baseline_stage_rmse_values_rpm=baseline,
        baseline_stage_rmse_relative_range=(max(baseline)-min(baseline))/mean(baseline),
        bootstrapped_next_states_without_exact_logged_successor=without_successor,
        truncated_training_prefixes=sum(r["truncated"] for r in training),
        median_transition_duration_ms=statistics.median(r["transition_duration_ms"] for r in training),
        discount_half_life_decisions=math.log(.5)/math.log(.99),
        trials=per_trial,performance_claim_allowed=False,deployment_allowed=False,
        direct_integrator_diagnostic="Trapezoidal replay of (actual Ki-baseline Ki)*observed error using 20ms snapshots. Not a simulated counterfactual, full 1ms integral or measured current change.",
        limitations=["128 replay windows are not 128 independent motor experiments",
                     f"Only {ki_changes} nonzero Ki training decisions; most actions hold existing gains",
                     "All four configurations still have inconsistent Kp signs across seeds",
                     "Critic agreement improvement does not imply speed RMSE improvement",
                     "Only startup-end RunStage observed at 1000 rpm, no new-policy physical evidence"])
    long_path=task/"convergence-study/response-training-summary.json"
    if long_path.exists():
        long=json.loads(long_path.read_text(encoding="utf-8"))
        report["longer_fitting"]={
            "steps_per_seed":400,"total_gradient_steps":long["total_gradient_steps"],
            "kp_direction_consistent":long["seed_kp_action_direction_consistent"],
            "kp_action_means":[s["validation_after"]["action_mean"][0] for s in long["seed_reports"]],
            "logged_critic1_q_means":[s["validation_after"]["logged_q_mean"][0] for s in long["seed_reports"]],
            "critic_disagreement_mean":mean(s["validation_after"]["critic_disagreement_mean"] for s in long["seed_reports"]),
            "physical_performance_verified":False,
        }
    (task/"noise-analysis.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(report,allow_nan=False))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--task",required=True);p.add_argument("--batch",required=True)
    args=p.parse_args()
    task=Path(args.task).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in task.parents
    analyze(task,args.batch)
