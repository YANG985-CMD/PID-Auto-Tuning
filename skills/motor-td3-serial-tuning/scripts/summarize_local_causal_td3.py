"""Summarize local diagnostics without publishing or accessing the motor."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(root):
    root=Path(root).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in root.parents
    source=load(root/"stitched/window-summary.json")
    records=[];configs={};steps=0
    for name in ("stitched-delta","delta-standardized","absolute-engineering","absolute-standardized"):
        summary=load(root/name/("response-training-summary.json" if name=="stitched-delta" else "causal-training-summary.json"))
        assert summary["dataset_sha256"]==source["dataset_sha256"] and not summary["deployment_allowed"]
        steps+=summary["total_gradient_steps"];group=[]
        for seed in summary["seed_reports"]:
            m=seed["validation_after"]
            checkpoint=next(p for p in (root/name).glob("*.mat") if p.stem.endswith("-"+str(seed["seed"])))
            assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==seed["checkpoint_sha256"]
            assert seed["actor_weight_change_l2"]>0 and all(v>0 for v in seed["critic_weight_change_l2"])
            r=dict(config=name,seed=seed["seed"],kp_action_mean=m["action_mean"][0],
                ki_action_mean=m["action_mean"][1],critic_disagreement=m["critic_disagreement_mean"],
                critic1_residual=m["online_bellman_residual_rmse"][0],
                critic2_residual=m["online_bellman_residual_rmse"][1],
                checkpoint_sha256=seed["checkpoint_sha256"],hardware_writeback=False)
            records.append(r);group.append(r)
        configs[name]=dict(kp_mean_actions=[r["kp_action_mean"] for r in group],
            ki_mean_actions=[r["ki_action_mean"] for r in group],
            critic_disagreement_mean=statistics.mean(r["critic_disagreement"] for r in group),
            critic1_residual_mean=statistics.mean(r["critic1_residual"] for r in group),
            critic2_residual_mean=statistics.mean(r["critic2_residual"] for r in group))
    with (root/"local-ablation.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]),lineterminator="\n");w.writeheader();w.writerows(records)
    ensemble=[];recommendations=[]
    for seed in (7,17,27):
        with (root/"absolute-engineering"/f"validation-seed-{seed}.csv").open(encoding="utf-8-sig") as f:
            rs=list(csv.DictReader(f))
        keys=[(r["boot_id"],int(r["telemetry_seq"])) for r in rs]
        if not ensemble:reference=keys
        else:assert keys==reference
        gain=[(float(r["candidate_kp"]),float(r["candidate_ki"])) for r in rs]
        ensemble.append(gain)
        recommendations.append(dict(seed=seed,mean_kp=statistics.mean(a for a,b in gain),
            mean_ki=statistics.mean(b for a,b in gain),kp_range=[min(a for a,b in gain),max(a for a,b in gain)],
            ki_range=[min(b for a,b in gain),max(b for a,b in gain)]))
    medians=[]
    for i,(boot,seq) in enumerate(reference):
        pairs=[values[i] for values in ensemble]
        medians.append(dict(boot_id=boot,telemetry_seq=seq,
            median_kp=statistics.median(a for a,b in pairs),median_ki=statistics.median(b for a,b in pairs),
            kp_seed_range=max(a for a,b in pairs)-min(a for a,b in pairs),
            ki_seed_range=max(b for a,b in pairs)-min(b for a,b in pairs),hardware_writeback=False))
    with (root/"local-ensemble-suggestions.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(medians[0]),lineterminator="\n");w.writeheader();w.writerows(medians)
    rows=[json.loads(s) for s in (root/"stitched/response-windows.jsonl").read_text().splitlines()]
    train=[r for r in rows if not r["validation_split"]]
    sources={(r["boot_id"],r["t_state_us"]) for r in train}
    unsupported=sum((r["boot_id"],r["t_next_us"]) not in sources for r in train)
    report=dict(schema_version=1,github_updated=False,hardware_accessed=False,
        additional_motor_trials=0,source_sessions=source["source_sessions"],
        repaired_training_continuations=sum(not r["validation_split"] for r in load(root/"stitched/stitch-audit.json")["repaired"]),
        repaired_validation_continuations=sum(r["validation_split"] for r in load(root/"stitched/stitch-audit.json")["repaired"]),
        additional_replay_rows=0,training_windows=len(train),validation_windows=len(rows)-len(train),
        next_states_without_exact_logged_successor=unsupported,
        remaining_truncated_training_prefixes=sum(r["truncated"] for r in train),
        td3_training_performed=True,candidates=len(records),total_gradient_steps=steps,configs=configs,
        diagnosis_preferred_config="absolute-engineering",absolute_gain_recommendations=recommendations,
        selection_basis="Cross-seed numerical consistency only; no counterfactual motor performance estimate",
        recommended_configuration_is_physically_approved=False,
        candidate_admission_allowed=False,deployment_allowed=False,performance_claim_allowed=False,
        ordinary_live_admission=False,thermal_gate_modified=False,
        runtime_compatible=False,ki_baseline=.00144,
        limitations=["Stable suggestions do not establish >=5% real motor RMSE improvement",
                     "Current ordinary deployment gate remains closed",
                     "Models have experimentalAgent instead of agent and cannot use the current live loader",
                     "Absolute actions retain the original physical delta-action reward cost",
                     "No termination or interpolated state was fabricated"])
    (root/"local-summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(report,allow_nan=False))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",required=True)
    run(p.parse_args().root)
