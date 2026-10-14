"""Descriptive metrics with identical reference/response-position weights.

Cells are repeated observations within one physical boot, not independent
trials. This utility neither estimates significance nor admits a policy.
"""
import math
from statistics import mean


def matched_metrics(rows, levels):
    if len(rows) != 45 or {r['slot'] for r in rows} != set(range(45)):
        raise ValueError('Expected 45 distinct response cells')
    for r in rows:
        if r['level'] not in levels or r['reference_phase'] != r['slot'] % 9 // 3:
            raise ValueError('Wrong gain or reference context')
        for key in ('response_mse_rpm2', 'peak_nominal_current_a', 'peak_speed_rpm'):
            if not math.isfinite(r[key]) or r[key] < 0:
                raise ValueError('Invalid measured metric')
    cells = []
    for phase in range(3):
        for position in range(3):
            groups = [[r for r in rows if r['reference_phase'] == phase
                       and r['slot'] % 3 == position and r['level'] == level]
                      for level in levels]
            if any(not group for group in groups):
                raise ValueError('Missing actual gain/context; do not interpolate')
            cells.append(dict(reference_phase=phase, position_ms=position * 400,
                counts=[len(group) for group in groups],
                mse=[mean(r['response_mse_rpm2'] for r in group) for group in groups],
                peak_current=[mean(r['peak_nominal_current_a'] for r in group) for group in groups],
                peak_speed=[mean(r['peak_speed_rpm'] for r in group) for group in groups]))
    scores = [dict(level=level,
        rmse_rpm=math.sqrt(mean(c['mse'][index] for c in cells)),
        mean_peak_nominal_current_a=mean(c['peak_current'][index] for c in cells),
        mean_peak_speed_rpm=mean(c['peak_speed'][index] for c in cells))
        for index, level in enumerate(levels)]
    baseline = scores[0]
    if baseline['rmse_rpm'] <= 0:
        raise ValueError('Undefined percentage improvement for zero baseline')
    for score in scores:
        score['rmse_improvement_fraction'] = (baseline['rmse_rpm'] - score['rmse_rpm']) / baseline['rmse_rpm']
        score['peak_current_difference_a'] = score['mean_peak_nominal_current_a'] - baseline['mean_peak_nominal_current_a']
        score['peak_speed_difference_rpm'] = score['mean_peak_speed_rpm'] - baseline['mean_peak_speed_rpm']
        score['descriptive_thresholds_met'] = (score['rmse_improvement_fraction'] >= .05
            and score['peak_current_difference_a'] <= 0 and score['peak_speed_difference_rpm'] <= 0)
    return dict(scores=scores, cells=cells, weighting='Equal weight over nine reference/position cells',
        inference='Single-boot descriptive comparison with possible carryover; no independent Actor proof',
        actor_admission=False, deployment_allowed=False, performance_claim_allowed=False)
