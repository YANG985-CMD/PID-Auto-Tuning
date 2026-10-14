"""Read-only audit of legacy physical snapshots and causal action ordering.

Legacy t_us is a guard tick; elapsed_ms was captured under the sensor lock.
Derive a separate snapshot interval with float32 rounding bounds. Never
rewrite raw packets, checkpoints or rewards, or authorize a policy release.
"""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from statistics import median


def capture_origin(packets):
    first=next((p for p in packets if p['enabled']),None)
    # BEGIN applies at guard.started_us and publishes applied_seq=0 before
    # the first GAINS command. Trial timing begins slightly later in the hook.
    if first is None or first['applied_seq']!=0 or first['t_apply_us']<=0:
        raise ValueError('Missing actual BEGIN readback for elapsed clock origin')
    return first['t_apply_us']


def snapshot_interval(packet, started_us):
    elapsed = packet['elapsed_ms']
    if not packet['enabled'] or not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError('Need an active, finite physical elapsed timestamp')
    # elapsed = float32(integer microseconds) / float32(1000). Includes both
    # rounding steps plus 1us integer quantization, with outward rounding.
    center = started_us + elapsed * 1000
    margin = max(2.0, abs(elapsed * 1000) * 2**-22 + 1)
    return center - margin, center + margin


def inspect(folder, stream=None):
    folder = Path(folder).resolve()
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    if not summary['passed'] or summary['final_irq_fault'] or summary['final_tx_fault']:
        raise ValueError('Only completed stopped trials can be audited')
    packets = [json.loads(line) for line in (folder/'telemetry.jsonl').read_text(encoding='utf-8').splitlines()]
    origin = capture_origin(packets)
    active = [p for p in packets if p['enabled']]
    if not active or len({p['boot_id'] for p in packets}) != 1:
        raise ValueError('Missing active packets or ambiguous boot')
    lookup = {p['seq']:p for p in packets}
    if len(lookup) != len(packets):
        raise ValueError('Duplicate packet sequence')
    deltas = [(sum(snapshot_interval(p,origin))/2-p['t_us']) for p in active]
    if min(deltas) < -5 or max(deltas) > 1500:
        raise ValueError('Unexpected clock discrepancy; do not normalize automatically')
    edges = json.loads((folder/'hall-edges.json').read_text(encoding='utf-8'))['records']
    if any(not e['valid'] or e['period_us'] <= 0 for e in edges):
        raise ValueError('Invalid Hall evidence')
    if any(b['edge'] != a['edge']+1 or b['t_us'] <= a['t_us'] for a,b in zip(edges,edges[1:])):
        raise ValueError('Non-contiguous Hall evidence')
    edge_times = [e['t_us'] for e in edges]
    certain = ambiguous = raw_mismatch = corrected_mismatch = 0
    for p in active:
        lo,hi = snapshot_interval(p,origin)
        j = bisect.bisect_right(edge_times,p['t_us'])-1
        a,b = bisect.bisect_right(edge_times,lo)-1,bisect.bisect_right(edge_times,hi)-1
        if min(j,a,b) < 1 or hi >= edge_times[-1]:
            continue
        raw_mismatch += abs(edges[j]['rpm']-p['speed']) > 1e-4
        if a != b:
            ambiguous += 1
            continue
        certain += 1
        corrected_mismatch += abs(edges[a]['rpm']-p['speed']) > 1e-4
    rows = []
    if stream:
        for path in sorted(Path(stream).glob('window-*.json')):
            w = json.loads(path.read_text(encoding='utf-8'))
            if w['boot_id'] != active[0]['boot_id']:
                raise ValueError('Window boot differs from raw trace')
            referenced = [*w['state_history'],*w['response']]
            if any(lookup.get(p['seq']) != p for p in referenced):
                raise ValueError('Window differs from immutable raw packet')
            source_hi = snapshot_interval(w['state'],origin)[1]
            source_command = next(c for c in w['commands'] if c['command_seq']==w['first_command_seq'])
            actual = next(p for p in w['response'] if p['applied_seq']>=source_command['command_seq'])
            command_by_id = {c['command_seq']:c for c in w['commands']}
            failures = []
            if source_hi >= actual['t_apply_us']:
                failures.append('source_not_provably_before_actual_application')
            for p in w['response']:
                c = command_by_id.get(p['applied_seq'])
                if (c is None or p['t_apply_us']>=snapshot_interval(p,origin)[0]
                    or not c['source_t_us']<=p['t_apply_us']<=c['expires_us']
                    or [p['kp'],p['ki']]!=w['action_applied']):
                    failures.append('response_action_or_order_unproven')
            rows.append(dict(window=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                sequence=w['window_index'],ordering_proven=not failures,reasons=sorted(set(failures)),
                source_to_first_observed_application_lower_bound_us=actual['t_apply_us']-source_hi))
    return dict(boot_id=active[0]['boot_id'],trial=str(folder),active_packets=len(active),
        guard_started_us_from_begin_readback=origin,
        trial_hook_start_minus_guard_start_us=summary['trial_timing']['started_us']-origin,
        snapshot_minus_legacy_timestamp_us=dict(min=min(deltas),median=median(deltas),max=max(deltas)),
        hall_certain_samples=certain,hall_ambiguous_samples=ambiguous,
        raw_timestamp_speed_mismatches=raw_mismatch,derived_capture_speed_mismatches=corrected_mismatch,
        windows=len(rows),ordering_proven=sum(r['ordering_proven'] for r in rows),window_audit=rows,
        inputs_sha256={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                      for name in ('summary.json','telemetry.jsonl','hall-edges.json')})


def run(trials, streams, output):
    if len(trials)!=len(streams):
        raise ValueError('One optional stream path or - per trial')
    output = Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents or output.exists():
        raise ValueError('Use a fresh task temporary directory')
    results = [inspect(t,None if s=='-' else s) for t,s in zip(trials,streams)]
    if len({r['boot_id'] for r in results}) != len(results):
        raise ValueError('Duplicate physical boot')
    report = dict(source='immutable-real-motor-snapshot-time-audit',trials=results,
        windows_audited=sum(r['windows'] for r in results),
        ordering_proven=sum(r['ordering_proven'] for r in results),
        historical_raw_modified=False,checkpoint_modified=False,training_performed=False,
        historical_rewards_recomputed=False,hardware_accessed=False,
        deployment_allowed=False,performance_claim_allowed=False,
        limitation='Ordering audit alone does not repair state history, time weights or prove controller improvement.')
    output.mkdir(parents=True)
    (output/'timing-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='trials'}))
    for r in results:
        print(json.dumps({k:v for k,v in r.items() if k not in ('window_audit','inputs_sha256')}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trials',nargs='+',required=True)
    p.add_argument('--streams',nargs='+',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    run(a.trials,a.streams,a.output)
