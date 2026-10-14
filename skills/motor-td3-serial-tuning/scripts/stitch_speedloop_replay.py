"""Extend measured held-gain responses across rejected short lease windows.

No interpolation, duplicate experience, hardware access or policy deployment.
An extension ends exactly at the following accepted decision's source packet.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
from speedloop_response_windows import lines,state,temporal_mean,write


def extend(previous,following,telemetry):
    start,end=previous["t_next_us"],following["t_state_us"]
    if end==start:
        assert previous["next_state"]==following["state"]
        return previous,None
    assert end>start and previous["boot_id"]==following["boot_id"]
    target=previous["action_applied"]
    packets={p["t_us"]:p for p in telemetry}
    assert state(packets[end])==following["state"]
    gap=[p for p in telemetry if start<=p["t_us"]<=end]
    if not all(p["enabled"] and p["fault"]==0 and [p["kp"],p["ki"]]==target for p in gap):
        return previous,"Unproven held gain across rejected interval"
    interval=[p for p in telemetry if previous["t_state_us"]<=p["t_us"]<=end]
    assert all(b["seq"]==a["seq"]+1 and 0<b["t_us"]-a["t_us"]<=40000
               for a,b in zip(interval,interval[1:]))
    response=[p for p in interval if p["t_us"]>previous["t_effective_us"]]
    assert all(p["enabled"] and p["fault"]==0 and [p["kp"],p["ki"]]==target for p in response)
    assert all(abs(p["speed"])<1800 and p["current"]<2 and 18<=p["vbus"]<=30 for p in response)
    times=[p["t_us"] for p in response]
    rmse2=temporal_mean([(p["speed_ref"]-p["speed"])**2 for p in response],times)
    current=max(abs(p["current"]) for p in response)
    speed=max(abs(p["speed"]) for p in response)
    saturation=temporal_mean([float(abs(p["current"])>=1.98) for p in response],times)
    reward=-rmse2/1e6-.12*(current/2)**2-.08*max(0,(speed-1500)/300)**2-.10*saturation-.005*sum(a*a for a in previous["action_normalized"])
    r=dict(previous)
    r.update(t_next_us=end,telemetry_seq_end=following["telemetry_seq_start"],
        next_state=following["state"],next_observation=following["observation"],
        reward=reward,response_rmse_rpm=rmse2**.5,response_peak_current_a=current,
        response_peak_speed_rpm=speed,response_saturation_ratio=saturation,
        response_overshoot_rpm=max(0,max(p["speed"]-p["speed_ref"] for p in response)),
        response_sample_count=len(response),response_telemetry_seqs=[p["seq"] for p in response],
        response_ms=(end-r["t_effective_us"])/1000,
        observed_response_span_ms=(times[-1]-times[0])/1000,
        transition_duration_ms=(end-r["t_state_us"])/1000,
        max_frame_gap_ms=max(b["t_us"]-a["t_us"] for a,b in zip(interval,interval[1:]))/1000,
        observed_applied_command_seqs=sorted({p["applied_seq"] for p in response}),
        response_extension_ms=(end-start)/1000,
        pre_extension_t_next_us=previous["t_next_us"],pre_extension_reward=previous["reward"],
        time_scaled_discount_diagnostic=.99**((end-r["t_state_us"])/100000),
        response_extension_basis="Every raw packet keeps the previously read-back gain; following decision starts at exact endpoint")
    return r,None


def run(repository,source,output):
    repository,source,output=map(lambda p:Path(p).resolve(),(repository,source,output))
    assert Path("E:/simulink/_codex_tmp").resolve() in output.parents
    summary=json.loads((source/"window-summary.json").read_text(encoding="utf-8"))
    assert summary["window_profile"]=="strict" and not summary["exploratory_only"]
    assert hashlib.sha256((source/"response-windows.jsonl").read_bytes()).hexdigest()==summary["dataset_sha256"]
    rows=lines(source/"response-windows.jsonl")
    raw={}
    for name,digest in summary["raw_telemetry_sha256"].items():
        path=repository/name/"telemetry.jsonl"
        assert hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()==digest
        data=lines(path);raw[data[0]["boot_id"]]=data
    byboot=collections.defaultdict(list)
    for index,r in enumerate(rows):byboot[r["boot_id"]].append(index)
    repaired=[];refused=[]
    for boot,indices in byboot.items():
        for a,b in zip(indices,indices[1:]):
            r,reason=extend(rows[a],rows[b],raw[boot])
            if reason:refused.append(dict(boot_id=boot,t_next_us=rows[a]["t_next_us"],reason=reason))
            elif "response_extension_ms" in r:
                repaired.append(dict(boot_id=boot,run_index=r["run_index"],
                    telemetry_seq_start=r["telemetry_seq_start"],extension_ms=r["response_extension_ms"],
                    validation_split=r["validation_split"]))
            rows[a]=r
        samples=[seq for i in indices for seq in rows[i]["response_telemetry_seqs"]]
        assert len(samples)==len(set(samples)),"Extension reuses another decision's response"
    output.mkdir(parents=True,exist_ok=True)
    data=b"".join((json.dumps(r,allow_nan=False)+"\n").encode() for r in rows)
    (output/"response-windows.jsonl").write_bytes(data)
    summary.update(pre_stitch_dataset_sha256=summary["dataset_sha256"],
        dataset_sha256=hashlib.sha256(data).hexdigest(),data_revision="raw-held-gain-continuation-v2",
        repaired_continuations=len(repaired),refused_continuations=refused,
        additional_motor_trials=0,additional_replay_rows=0,performance_claim_allowed=False,
        response_sample_count_histogram=dict(collections.Counter(r["response_sample_count"] for r in rows)),
        observed_span_ms_range=[min(r["observed_response_span_ms"] for r in rows),max(r["observed_response_span_ms"] for r in rows)],
        transition_duration_ms_range=[min(r["transition_duration_ms"] for r in rows),max(r["transition_duration_ms"] for r in rows)])
    write(output/"window-summary.json",summary)
    write(output/"stitch-audit.json",dict(repaired=repaired,refused=refused,
        hardware_accessed=False,interpolated=False,added_rows=0))
    print(json.dumps(dict(repaired=len(repaired),refused=len(refused),
        train=summary["training_windows"],validation=summary["validation_windows"],
        dataset_sha256=summary["dataset_sha256"])))
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("repository","source","output"):p.add_argument("--"+name,required=True)
    args=p.parse_args();run(args.repository,args.source,args.output)
