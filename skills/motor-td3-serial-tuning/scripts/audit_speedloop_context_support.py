"""Audit phase/position coverage of retained real gain-response slots.

Context-standardized scores remain exploratory. They never replace primary
physical metrics, independent repeats, or Actor evaluation/deployment gates.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


def analyze(rows):
    if len(rows)!=45 or {r['slot'] for r in rows}!=set(range(45)):
        raise ValueError('Expected 45 distinct actual slots')
    for r in rows:
        if r['reference_phase']!=r['slot']%9//3 or r['level'] not in (0,1,2):
            raise ValueError('Reference context or gain label changed')
        if not math.isfinite(r['response_mse_rpm2']) or r['response_mse_rpm2']<0:
            raise ValueError('Invalid response MSE')
    cells=[]
    for phase in range(3):
        for position in range(3):
            values=[[r for r in rows if r['reference_phase']==phase and r['slot']%3==position and r['level']==arm]
                    for arm in range(3)]
            cells.append(dict(reference_phase=phase,speed_ref_rpm=[1100,900,1000][phase],
                position_after_reference_change_ms=position*400,counts=[len(v) for v in values],
                response_mse_rpm2=[mean(r['response_mse_rpm2'] for r in v) if v else None for v in values],
                source_error_rpm=[mean(r['source_error_rpm'] for r in v) if v else None for v in values]))
    missing=[dict(speed_ref_rpm=c['speed_ref_rpm'],position_after_reference_change_ms=c['position_after_reference_change_ms'],
        missing_gain_levels=[g for g,n in enumerate(c['counts']) if n==0]) for c in cells if min(c['counts'])==0]
    common=[c for c in cells if min(c['counts'])>0]
    scores=[]
    if common:
        for arm in range(3):
            # Each reference receives equal weight; inside it, weight only
            # its observed common positions equally. Missing cells are never
            # interpolated, relabeled, or silently filled with zero.
            byphase=[mean(c['response_mse_rpm2'][arm] for c in common if c['reference_phase']==p) for p in range(3)]
            scores.append(math.sqrt(mean(byphase)))
    result=dict(reference_position_cells=cells,missing_contexts=missing,common_cells=len(common),
        all_gain_levels_supported_in_all_contexts=not missing,
        exploratory_common_context_rmse_rpm=scores,
        exploratory_rmse_improvement_fraction=[(scores[0]-v)/scores[0] for v in scores] if scores else [],
        score_basis='Equal reference weights; within-reference equal common-position weights; single boot only',
        primary_metric_changed=False,missing_responses_synthesized=False,
        interpretation='Gain/reference balance does not imply balance over time since reference change or initial state',
        actor_admission=False,deployment_allowed=False,performance_claim_allowed=False)
    return result


def run(archive,output):
    archive,out=Path(archive).resolve(),Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    inputs=archive/'gain-effect';summary=json.loads((inputs/'gain-effect-summary.json').read_text(encoding='utf-8'))
    for name,key in [('telemetry.jsonl','telemetry_sha256'),('commands.jsonl','commands_sha256')]:
        if hashlib.sha256((archive/'trial'/name).read_bytes()).hexdigest()!=summary[key]:raise ValueError('Raw input changed')
    rows=json.loads((inputs/'slot-responses.json').read_text(encoding='utf-8'))
    result=analyze(rows)
    result.update(source='retained-real-motor-context-support-audit',hardware_accessed=False,
        source_boot_id=summary['boot_id'],actual_slots=45,
        slot_file_sha256=hashlib.sha256((inputs/'slot-responses.json').read_bytes()).hexdigest())
    out.mkdir(parents=True,exist_ok=False)
    (out/'context-support.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.archive,a.output)
