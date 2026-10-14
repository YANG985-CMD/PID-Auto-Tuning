"""Exact v25 baseline/+2% nine-second holds, late score, no Actor."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import speedloop_upper8_continuous as previous
from speedloop_duration_review import overrides

PATTERNS=((0,2),(2,0))
VERSION='upper8-continuous-plus2-longhold-late-score-v1'

@contextmanager
def context():
    with overrides(previous,PATTERNS=PATTERNS,PLATEAU_START_MS=4000,PLATEAU_MS=9000,
        PLATEAU_END_MS=22000,ANALYSIS_SETTLE_MS=7000,ANALYSIS_END_MARGIN_MS=200,VERSION=VERSION):
        yield

def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Same reviewed v25 only; no firmware change')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    if (cfg.get('hold_design')!=VERSION or cfg.get('gain_hold_seconds')!=9
        or cfg.get('post_actual_apply_wait_seconds')!=7
        or cfg.get('physical_behavior_probe_not_frozen_actor') is not True
        or cfg.get('probe_mode')!='upper8-continuous-plus2-longhold'
        or cfg.get('independent_performance_evaluation') is not True):
        raise ValueError('Predeclared complementary long hold and late score required')
    with context():return previous.validate(a)

def run(a):
    validate(a)
    with context():result=previous.run(a)
    result.update(hold_design=VERSION,gain_hold_seconds=9,post_actual_apply_wait_seconds=7,
        physical_behavior_probe_not_frozen_actor=True,firmware_unchanged=True,
        actor_applied=False,candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','adapter-checks','nm','schedule-contract','previous-trial-summary'):
        p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','debug-read-benchmark','bounded-reader-benchmark'):
        p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    p.add_argument('--debug-read-frequency-hz',default=4000000,type=int,choices=(4000000,))
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    for name in ('authorized-continuous-upper8-probe','energized-phase-inhibited-confirmed',
        'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();a.energized_update_authorized=False;a.fault_recovery_authorized=False
    if a.phase=='trial' and any(not getattr(a,n) for n in ('boot_token_file','stream_output','debug_read_benchmark','bounded_reader_benchmark')):
        p.error('Missing one-use trial evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
