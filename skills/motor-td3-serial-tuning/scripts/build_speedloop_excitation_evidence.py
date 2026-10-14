"""v12 changes Hall evidence capacity only; v11 control and limits remain.

832 records retain the first 4s reference step while reserving >=4KiB stack.
No hardware access, Actor, changed references, or longer motion budget.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_handover_excitation as previous
import build_speedloop_excitation_review as excitation
import build_speedloop_response_review as response
from build_g431_locked_foc import replace_once

IDENTITY = 'g431-speedloop-pi-excitation-evidence-8s-v12'
CAPACITY = 832
BASE_PATCH = excitation.BASE_PATCH


def patch_port(path, motion=False):
    BASE_PATCH(path, motion)
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, '#define HALL_TRACE_CAPACITY 768U',
                        f'#define HALL_TRACE_CAPACITY {CAPACITY}U')
    path.write_text(text, encoding='utf-8', newline='\n')


def build(a):
    saved = previous.IDENTITY, excitation.BASE_PATCH
    try:
        previous.IDENTITY = IDENTITY
        excitation.BASE_PATCH = patch_port
        report = previous.build(a)
    finally:
        previous.IDENTITY, excitation.BASE_PATCH = saved
    sections = report['image_sections_bytes']
    used = sections['data'] + sections['bss']
    assert 32768-used >= 4096, 'Reserve 4KiB for stack'
    report['hall_trace_capacity'] = CAPACITY
    report['evidence_review'] = dict(
        control_equivalent_to='g431-speedloop-pi-handover-excitation-8s-v11',
        control_modified=False, limits_modified=False,
        hall_trace_capacity=CAPACITY, stack_reserve_bytes=32768-used,
        earlier_raw_stage_proof_required=True, actor_allowed=False)
    (Path(a.output)/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'arm-bin'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--compiler', default='gcc')
    p.add_argument('--temp-root', default='E:/simulink/_codex_tmp')
    build(p.parse_args())
