"""Publish an immutable follow-up study and physical shutdown evidence.

No CAN, serial, debugger or training access. Raw private boot-token files and
one-time stdout stay outside the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from publish_speedloop_offline_study import output_closed
from select_td3_candidate import select


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def publish_batch(task, dest):
    source=task/"physical-batch"
    batch=load(source/"collection-summary.json")
    assert batch["passed"] and batch["completed_rounds"]==6 and batch["failure"] is None
    rounds=sorted(source.glob("round-*"));assert len(rounds)==6
    records={}
    for folder in rounds:
        s=load(folder/"trial/summary.json")
        assert s["passed"] and s["final_irq_fault"]==s["final_tx_fault"]==0
        assert s["protocol_stop_acknowledged"] and output_closed(s)
        assert s["core_halted_after_physical_shutdown"] and s["can_released_after_shutdown"]
        assert s["maximum_motion_seconds"]==3 and s["speed_ref_rpm"]==1000
        assert all(abs(kp-.003389)<1e-9 for kp,ki in s["gain_pairs"])
        if s["comparison_policy"]=="baseline":
            assert len(s["gain_pairs"])==1 and abs(s["gain_pairs"][0][1]-.00144)<1e-9
        out=dest/"physical-batch"/folder.name;out.mkdir(parents=True,exist_ok=True)
        copies={name:folder/"trial"/name for name in
                ("summary.json","telemetry.jsonl","commands.jsonl","hall-edges.json")}
        copies["prepare-summary.json"]=folder/"prepare/summary.json"
        copies.update({name:task/"audit"/folder.name/name for name in
                       ("analysis.json","experience-candidates.jsonl","telemetry.csv")})
        for name,path in copies.items():
            records[f"physical-batch/{folder.name}/{name}"]=hashlib.sha256(path.read_bytes()).hexdigest()
            (out/name).write_bytes(canonical(path))
    write(dest/"physical-batch/collection-summary.json",batch)
    write(dest/"original-byte-sha256.json",records)


def publish_results(repository,task,dest):
    strict=load(task/"strict/window-summary.json")
    assert strict["window_profile"]=="strict" and not strict["exploratory_only"]
    for name in ("response-windows.jsonl","window-summary.json","rejected-groups.json"):
        out=dest/"strict"/name;out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(canonical(task/"strict"/name))
    root=task/"noise-study";study=load(root/"study-summary.json")
    assert study["dataset_sha256"]==strict["dataset_sha256"]
    updated=[]
    for config in study["configs"]:
        name=config["name"];source=root/name;out=dest/"noise-study"/name
        out.mkdir(parents=True,exist_ok=True)
        report=load(source/"response-training-summary.json");report["candidate_files"]=[]
        for file in source.glob("*"):
            if file.suffix in (".json",".csv") and file.name!="response-training-summary.json":
                (out/file.name).write_bytes(canonical(file))
        for seed in report["seed_reports"]:
            filename=f'response-candidate-seed-{seed["seed"]}.mat'
            model=repository/"models"/dest.name/name/filename
            model.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/filename,model)
            assert hashlib.sha256(model.read_bytes()).hexdigest()==seed["checkpoint_sha256"]
            report["candidate_files"].append(model.relative_to(repository).as_posix())
        write(out/"response-training-summary.json",report)
        old=repository/"examples/speedloop-v5-real-20261012/offline-study-20261012/bound-old-policy-comparison.json"
        gate=select(out/"response-training-summary.json",old,out/"candidate-selection.json",quiet=True)
        gate["training_summary"]="response-training-summary.json"
        gate["repeated_comparison"]="../../../offline-study-20261012/bound-old-policy-comparison.json"
        write(out/"candidate-selection.json",gate);updated.append(report)
    study["reports"]=updated;write(dest/"noise-study/study-summary.json",study)
    for name in ("study-contract.json","ablation.csv"):
        if (root/name).exists():(dest/"noise-study"/name).write_bytes(canonical(root/name))
    supplement_steps=0
    source=task/"convergence-study"
    if source.exists():
        out=dest/"convergence-study";out.mkdir(parents=True,exist_ok=True)
        report=load(source/"response-training-summary.json");report["candidate_files"]=[]
        assert report["dataset_sha256"]==strict["dataset_sha256"]
        for file in source.glob("*"):
            if file.suffix in (".json",".csv") and file.name!="response-training-summary.json":
                (out/file.name).write_bytes(canonical(file))
        for seed in report["seed_reports"]:
            filename=f'response-candidate-seed-{seed["seed"]}.mat'
            model=repository/"models"/dest.name/"convergence-study"/filename
            model.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/filename,model)
            assert hashlib.sha256(model.read_bytes()).hexdigest()==seed["checkpoint_sha256"]
            report["candidate_files"].append(model.relative_to(repository).as_posix())
        write(out/"response-training-summary.json",report)
        old=repository/"examples/speedloop-v5-real-20261012/offline-study-20261012/bound-old-policy-comparison.json"
        gate=select(out/"response-training-summary.json",old,out/"candidate-selection.json",quiet=True)
        gate["training_summary"]="response-training-summary.json"
        gate["repeated_comparison"]="../../offline-study-20261012/bound-old-policy-comparison.json"
        write(out/"candidate-selection.json",gate)
        supplement_steps=report["total_gradient_steps"]
    for name in ("dependency-preflight.json","matlab-noise-tests.json","matlab-native-tests.json","python-followup-tests.json",
                 "data-audit-summary.json","noise-analysis.json","matlab-replay-check.json",
                 "offline-actor-suggestions.csv","suggestions-summary.json"):
        if (task/name).exists():(dest/name).write_bytes(canonical(task/name))
    manifest={p.relative_to(dest).as_posix():hashlib.sha256(canonical(p)).hexdigest()
              for p in dest.rglob("*") if p.is_file() and p.name!="published-sha256.json"}
    write(dest/"published-sha256.json",{"convention":"Git UTF-8 LF blobs","files":manifest})
    print(json.dumps(dict(source_sessions=strict["source_sessions"],
        strict_training_windows=strict["training_windows"],validation_windows=strict["validation_windows"],
        native_td3_steps=study["total_gradient_steps"]+supplement_steps,published_files=len(manifest),deployment_allowed=False)))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("repository","task","name"):p.add_argument("--"+name,required=True)
    p.add_argument("--batch-only",action="store_true")
    args=p.parse_args();repo=Path(args.repository).resolve();task=Path(args.task).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in task.parents
    assert args.name and Path(args.name).name==args.name and args.name not in (".","..")
    dest=repo/"examples/speedloop-v5-real-20261012"/args.name
    publish_batch(task,dest)
    if not args.batch_only:publish_results(repo,task,dest)
