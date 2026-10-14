"""Two bounded v25 data captures that cover reachable source/target pairs."""
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import speedloop_upper8_continuous as previous
from speedloop_duration_review import overrides

def _cycle():
    adjacency={v:[w for w in (0,2,4,6,8) if 0<abs(v-w)<=4] for v in (0,2,4,6,8)}
    stack=[0];trail=[]
    while stack:
        v=stack[-1]
        if adjacency[v]:stack.append(adjacency[v].pop())
        else:trail.append(stack.pop())
    return tuple(reversed(trail))

CYCLE=_cycle()
PATTERN=CYCLE+CYCLE[1:]+(2,4,0)
PATTERNS=(PATTERN,tuple(reversed(PATTERN)))
VERSION='upper8-dense-reachable-pairs-switching-v1'

def planned_pair_counts(pattern):
    return Counter(zip(pattern,pattern[1:]))

@contextmanager
def context():
    with overrides(previous,PATTERNS=PATTERNS,PLATEAU_START_MS=6000,PLATEAU_MS=500,
        PLATEAU_END_MS=22000,ANALYSIS_SETTLE_MS=100,ANALYSIS_END_MARGIN_MS=50,VERSION=VERSION):
        yield

def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Exact existing v25; no flash entry')
    if not getattr(a,'authorized_dense_switch_probe',False):raise ValueError('Fresh bounded dense-capture authorization required')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    if (cfg.get('gain_pair_design')!=VERSION or cfg.get('actual_switch_interval_ms')!=500
        or cfg.get('independent_performance_evaluation') is not False
        or cfg.get('training_purpose')!='actual-source-gain-switch-response'
        or cfg.get('probe_mode')!='upper8-switching'
        or cfg.get('actor_applied') is not False or cfg.get('thermal_gate_modified') is not False):
        raise ValueError('Training-only switching contract, fixed Ki and unchanged protection required')
    for pattern in PATTERNS:
        pairs=planned_pair_counts(pattern)
        expected={(v,w) for v in (0,2,4,6,8) for w in (0,2,4,6,8) if 0<abs(v-w)<=4}
        if len(pattern)!=32 or pattern[0]!=0 or pattern[-1]!=0 or set(pairs)!=expected or min(pairs.values())<2:
            raise ValueError('Predeclared reachable-pair coverage changed')
    with context():return previous.validate(a)

def run(a):
    validate(a)
    with context():result=previous.run(a)
    result.update(gain_pair_design=VERSION,actual_switch_interval_ms=500,
        independent_performance_evaluation=False,transient_training_capture=True,
        physical_behavior_probe_not_frozen_actor=True,firmware_unchanged=True,
        actor_applied=False,candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result
