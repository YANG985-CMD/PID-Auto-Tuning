"""Publish response-window audits and experimental weights; no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from select_td3_candidate import select


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,indent=2,allow_nan=False)+"\n").encode())


def canonical(path):
    return path.read_bytes().replace(b"\r\n",b"\n")


def publish(repository,task):
    repository,task=Path(repository).resolve(),Path(task).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in task.parents
    dest=repository/"examples/speedloop-v5-real-20261012/response-window-20261012"
    for profile in ("strict","exploratory"):
        out=dest/profile;out.mkdir(parents=True,exist_ok=True)
        for name in ("response-windows.jsonl","window-summary.json","rejected-groups.json"):
            (out/name).write_bytes(canonical(task/profile/name))
        training=load(task/f"{profile}-training"/"response-training-summary.json")
        training["candidate_files"]=[]
        for file in (task/f"{profile}-training").glob("*.json"):
            if file.name!="response-training-summary.json":
                (out/file.name).write_bytes(canonical(file))
        for file in (task/f"{profile}-training").glob("*.csv"):
            (out/file.name).write_bytes(canonical(file))
        for seed in training["seed_reports"]:
            name=f'response-candidate-seed-{seed["seed"]}.mat'
            model=repository/"models/response-window-20261012"/name
            model.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(task/f"{profile}-training"/name,model)
            assert hashlib.sha256(model.read_bytes()).hexdigest()==seed["checkpoint_sha256"]
            training["candidate_files"].append(model.relative_to(repository).as_posix())
        write(out/"response-training-summary.json",training)
        if training["seed_reports"]:
            repeated=repository/"examples/speedloop-v5-real-20261012/offline-study-20261012/bound-old-policy-comparison.json"
            gate=select(out/"response-training-summary.json",repeated,out/"candidate-selection.json",quiet=True)
            gate["training_summary"]="response-training-summary.json"
            gate["repeated_comparison"]="../../offline-study-20261012/bound-old-policy-comparison.json"
            write(out/"candidate-selection.json",gate)
    for name in ("dependency-preflight.json","matlab-response-tests.json","python-response-tests.json",
                 "offline-actor-suggestions.csv","suggestions-summary.json"):
        (dest/name).write_bytes(canonical(task/name))
    summary=load(dest/"physical-batch/collection-summary.json")
    assert summary["passed"] and summary["completed_rounds"]==6
    for round_dir in (dest/"physical-batch").glob("round-*"):
        s=load(round_dir/"summary.json");g=s["final_board_state"]
        assert s["passed"] and s["protocol_stop_acknowledged"] and s["final_irq_fault"]==0 and s["final_tx_fault"]==0
        assert s["core_halted_after_physical_shutdown"] and s["can_released_after_shutdown"]
        assert not g["tim1_bdtr"]&0x8000 and not g["tim1_ccer"]&0x555
        assert g["gpioa_moder"]&0x3f0000==0x150000 and g["gpiob_moder"]&0xfc000000==0x54000000
        assert not g["gpioa_odr"]&0x700 and not g["gpiob_odr"]&0xe000
        assert all(abs(kp-.003389)<1e-9 for kp,ki in s["gain_pairs"])
        if s["comparison_policy"]=="baseline":
            assert len(s["gain_pairs"])==1 and abs(s["gain_pairs"][0][1]-.00144)<1e-9
    files={p.relative_to(dest).as_posix():hashlib.sha256(canonical(p)).hexdigest()
           for p in dest.rglob("*") if p.is_file() and p.name!="published-sha256.json"}
    write(dest/"published-sha256.json",{"convention":"Git UTF-8 LF blobs","files":files})
    print(json.dumps({"physical_rounds":6,"source_sessions":41,"raw_short_windows":369,
                      "strict_training_windows":106,"exploratory_training_windows":146,
                      "native_td3_steps":240,"deployment_allowed":False,"published_files":len(files)}))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository",required=True);p.add_argument("--task",required=True)
    args=p.parse_args();publish(args.repository,args.task)
