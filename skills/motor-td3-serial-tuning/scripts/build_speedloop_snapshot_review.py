"""Offline v17: timestamp the locked physical snapshot, not a prior guard tick.

Only private collection sources change. No hardware access or Actor release.
Original FOC, PI, reference schedule and all trip/lease limits remain v16.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_ki_review as previous
from build_g431_locked_foc import replace_once

IDENTITY = 'g431-speedloop-pi-snapshot-24s-v17'
BASE_PATCH = previous.patch_port


def patch_port(path, motion=False):
    BASE_PATCH(path, motion)
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, '    memset(t,0,sizeof(*t));', '''    memset(t,0,sizeof(*t));
    /* Interrupts remain disabled through all physical fields. Record the
     * actual snapshot instant; the guard's previous tick can be ~1 ms old. */
    t->t_us=clock_us();''')
    text = replace_once(text,
        't->elapsed_ms=endpoint.guard.enabled?(float)(clock_us()-endpoint.guard.started_us)/1000.0f:0.0f;',
        't->elapsed_ms=endpoint.guard.enabled?(float)(t->t_us-endpoint.guard.started_us)/1000.0f:0.0f;')
    path.write_text(text, encoding='utf-8', newline='\n')
    control = path.parent / 'motor_td3_can_control.c'
    text = control.read_text(encoding='utf-8')
    text = replace_once(text,
        '    t.seq=++c->telemetry_seq; t.t_us=c->guard.last_tick_us; t.t_apply_us=c->guard.t_apply_us;',
        '''    /* Caller serializes the snapshot and guard metadata. A regressing
     * capture clock is rejected; never relabel new sensor data as an old tick. */
    if(t.t_us<c->guard.last_tick_us || t.t_us<c->guard.t_apply_us) return 0;
    t.seq=++c->telemetry_seq; t.t_apply_us=c->guard.t_apply_us;''')
    control.write_text(text, encoding='utf-8', newline='\n')


def build(args):
    saved = previous.IDENTITY, previous.patch_port
    try:
        previous.IDENTITY = IDENTITY
        previous.patch_port = patch_port
        result = previous.build(args)
    finally:
        previous.IDENTITY, previous.patch_port = saved
    result['snapshot_review'] = dict(timestamp_source='physical snapshot inside IRQ lock',
        elapsed_and_timestamp_same_capture=True, rejects_capture_clock_regression=True,
        telemetry_wire_layout_changed=False, sampling_cadence_changed=False,
        control_changed=False, protection_limits_changed=False, actor_allowed=False,
        deployment_allowed=False, performance_claim_allowed=False,
        historical_timestamp_audit_required=True)
    (Path(args.output) / 'summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'arm-bin'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--compiler', default='gcc')
    p.add_argument('--temp-root', default='E:/simulink/_codex_tmp')
    build(p.parse_args())
