"""Existing exact v23 image: gain phase coverage without changing protections."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import speedloop_reference_v23 as previous
from speedloop_duration_review import overrides

# Each 2s reference cell contains base, low and high. The baseline phases are
# exchanged between repeated references within each boot, rather than always
# assigning base to the same mechanical recovery phase.
CELL_PATTERNS=((0,1,0,2),(1,0,2,0),(0,2,0,1),(2,0,1,0))
CELL_ORDER=(0,0,2,1,1,3,3,2)
PATTERN=tuple(level for cell in CELL_ORDER for level in CELL_PATTERNS[cell])
PATTERNS=(PATTERN,tuple(3-level if level else 0 for level in PATTERN))
VERSION='reference-phase-balanced-local4-v1'


@contextmanager
def context():
    with overrides(previous.base,SWITCH_PATTERNS=PATTERNS):
        yield


def validate(a):
    if a.phase not in ('prepare','trial'):
        raise ValueError('Existing v23 image only; no Flash operation')
    cfg=json.loads(Path(a.schedule_contract).read_text(encoding='utf-8'))
    if (cfg.get('gain_phase_design')!=VERSION or cfg.get('pattern')!=list(PATTERNS[a.schedule_index])
        or cfg.get('gain_phase_coverage_fit_split')!='predeclared independently in every boot'
        or cfg.get('independent_performance_evaluation') is not False
        or cfg.get('actor_applied') is not False):
        raise ValueError('Predeclared phase coverage contract required')
    with context():
        return previous.validate(a)


def run(a):
    validate(a)
    with context():
        result=previous.run(a)
    result.update(gain_phase_design=VERSION,gain_phase_cell_order=list(CELL_ORDER),
        orchestrator_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        candidate_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','trial'))
    for name in ('build','output','adapter-checks','nm','schedule-contract','previous-trial-summary'):
        p.add_argument('--'+name,required=True)
    for name in ('boot-token-file','stream-output','debug-read-benchmark'):
        p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--schedule-index',default=0,type=int,choices=(0,1))
    p.add_argument('--hall-read-profile',default='pipelined-v1',choices=('pipelined-v1',))
    p.add_argument('--debug-read-frequency-hz',default=4000000,type=int,choices=(4000000,))
    p.add_argument('--gain-mode',default='kp_probe',choices=('kp_probe',))
    for name in ('authorized-reference-steps','energized-update-authorized',
        'energized-phase-inhibited-confirmed','power-disconnected-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.phase=='trial' and (not a.boot_token_file or not a.stream_output):
        p.error('One-use token and journal required')
    raise SystemExit(0 if run(a)['passed'] else 1)
