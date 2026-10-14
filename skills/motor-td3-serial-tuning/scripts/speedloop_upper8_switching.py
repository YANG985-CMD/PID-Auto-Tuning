"""Two finite complementary upper8 switching captures on unchanged v24."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import speedloop_upper8_probe as previous
from speedloop_duration_review import overrides

PATTERN=(0,1,2,1,0,2)*5+(0,1)
PATTERNS=(PATTERN,tuple(2-level for level in PATTERN))
VERSION='upper8-three-held-gains-switching-v1'

@contextmanager
def context():
    with overrides(previous,PATTERNS=PATTERNS,PLATEAU_MS=500,
        ANALYSIS_SETTLE_MS=100,ANALYSIS_END_MARGIN_MS=50):yield

def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Exact existing v24 only; no flashing')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    if (cfg.get('gain_pair_design')!=VERSION or cfg.get('actual_switch_interval_ms')!=500
        or cfg.get('independent_performance_evaluation') is not False
        or cfg.get('training_purpose')!='actual-source-gain-switch-response'
        or cfg.get('whole_boot_role') not in ('train','validation')
        or cfg.get('batch_maximum_rounds')!=2 or cfg.get('batch_motion_budget_seconds')!=48
        or cfg.get('fault_ends_entire_batch') is not True):
        raise ValueError('Finite two-round actual switching experiment required')
    with context():return previous.validate(a)

def run(a):
    validate(a)
    with context():result=previous.run(a)
    if a.phase=='trial':
        result.update(gain_pair_design=VERSION,actual_switch_interval_ms=500,
            independent_performance_evaluation=False,actor_applied=False,
            candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
        (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','adapter-checks','nm','schedule-contract','previous-trial-summary'):
        p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','debug-read-benchmark'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    p.add_argument('--debug-read-frequency-hz',default=4000000,type=int,choices=(4000000,))
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    for name in ('authorized-upper8-probe','energized-phase-inhibited-confirmed',
        'power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args();a.energized_update_authorized=False
    if a.phase=='trial' and any(not getattr(a,n) for n in ('boot_token_file','stream_output','debug_read_benchmark')):
        p.error('Missing one-use trial evidence')
    raise SystemExit(0 if run(a)['passed'] else 1)
