#!/usr/bin/env python3
"""Compare four bounded speed-loop tuning methods on one deterministic plant.

The experiment is simulation-only.  It uses the same mock plant and fixtures
for the bounded AI skill search, fuzzy PI scheduler, supervised NN-PID
scheduler, and a MATLAB TD3 evaluation report.  No board, CAN channel, or
Flash operation is opened by this script.
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


KP_BASE, KI_BASE = 0.003389, 0.00144
KP_LO, KP_HI = 0.0025, 0.0043
KI_LO, KI_HI = 0.0008, 0.0022
MAX_PEAK_CURRENT = 3.0
MAX_OVERSHOOT_RPM = 120.0
SPEED_REFS = (500.0, 800.0, 1100.0)
TEST_SEEDS = (101, 202, 303)
TRAIN_SEEDS = (11, 22, 33, 44, 55, 66)
WINDOWS = 30
INNER_STEPS = 20
DT = 0.005
FUZZY_CENTERS = np.linspace(-1.0, 1.0, 7)


def _make_fuzzy_rules():
    """Build symmetric gain-increment surfaces for the 7x7 fuzzy scheduler."""
    e, de = np.meshgrid(FUZZY_CENTERS, FUZZY_CENTERS, indexing='ij')
    magnitude = np.clip(0.7 * np.abs(e) + 0.3 * np.abs(de), 0.0, 1.0)
    delta_kp = 0.6 * magnitude
    delta_ki = 0.5 * (1.0 - 2.0 * np.abs(e)) - 0.2 * np.abs(de)
    return delta_kp, np.clip(delta_ki, -0.5, 0.5)


FUZZY_DKP_RULE, FUZZY_DKI_RULE = _make_fuzzy_rules()


def clip(value, lo, hi):
    return max(lo, min(hi, float(value)))


def fixed_policy(kp, ki):
    def policy(_):
        return float(kp), float(ki)
    return policy


def _membership_vector(value):
    """Seven overlapping triangular/trapezoidal memberships on [-1, 1]."""
    x = clip(value, -1.0, 1.0)
    memberships = np.zeros(7, dtype=float)
    for index, center in enumerate(FUZZY_CENTERS):
        if index == 0:
            memberships[index] = 1.0 if x <= center else max(0.0, (FUZZY_CENTERS[1] - x) /
                                                               (FUZZY_CENTERS[1] - center))
        elif index == len(FUZZY_CENTERS) - 1:
            memberships[index] = 1.0 if x >= center else max(0.0, (x - FUZZY_CENTERS[-2]) /
                                                               (center - FUZZY_CENTERS[-2]))
        else:
            left, right = FUZZY_CENTERS[index - 1], FUZZY_CENTERS[index + 1]
            memberships[index] = max(0.0, min((x - left) / (center - left),
                                              (right - x) / (right - center)))
    total = float(memberships.sum())
    return memberships / total if total > 0.0 else np.array([0, 0, 0, 1, 0, 0, 0], dtype=float)


def fuzzy_gains(ctx):
    """Mamdani-like 7x7 fuzzy gain scheduler with weighted-centroid outputs."""
    ref = max(abs(ctx['ref']), 1.0)
    error = ctx['ref'] - ctx['speed']
    de = error - ctx['previous_error']
    e_norm = clip(error / max(ref, 1000.0), -1.0, 1.0)
    de_norm = clip(de / max(ref, 1000.0), -1.0, 1.0)
    activation = np.outer(_membership_vector(e_norm), _membership_vector(de_norm))
    denominator = float(activation.sum())
    delta_kp = float((activation * FUZZY_DKP_RULE).sum() / denominator)
    delta_ki = float((activation * FUZZY_DKI_RULE).sum() / denominator)
    kp = KP_BASE * (1.0 + delta_kp)
    ki = KI_BASE * (1.0 + delta_ki)
    return clip(kp, KP_LO, KP_HI), clip(ki, KI_LO, KI_HI)


class NnPid:
    """Small supervised NN-PID scheduler trained to reproduce fuzzy gains."""
    def __init__(self, seed=7):
        self.rng = np.random.default_rng(seed)
        self.w1 = self.rng.normal(0, 0.15, (5, 16))
        self.b1 = np.zeros(16)
        self.w2 = self.rng.normal(0, 0.15, (16, 16))
        self.b2 = np.zeros(16)
        self.w3 = self.rng.normal(0, 0.15, (16, 2))
        self.b3 = np.zeros(2)
        self.loss = None
        self.validation_loss = None

    @staticmethod
    def features(ref, speed, previous_error, integral):
        scale = max(abs(ref), 1000.0)
        return np.array([[(ref - speed) / scale, (ref - speed - previous_error) / scale,
                          clip(integral / 2.0, -1, 1), speed / 1200.0,
                          ref / 1200.0]], dtype=float)

    def forward(self, x):
        z1 = np.tanh(x @ self.w1 + self.b1)
        z2 = np.tanh(z1 @ self.w2 + self.b2)
        y = np.tanh(z2 @ self.w3 + self.b3)
        return y, (x, z1, z2, y)

    def fit(self, samples, validation_samples=None, epochs=900, lr=0.02):
        x = np.vstack([s[0] for s in samples])
        target = np.vstack([s[1] for s in samples])
        for _ in range(epochs):
            y, cache = self.forward(x)
            err = y - target
            dy = 2.0 * err / len(x)
            x0, z1, z2, y0 = cache
            dz3 = dy * (1.0 - y0 * y0)
            dw3 = z2.T @ dz3; db3 = dz3.sum(axis=0)
            dz2 = (dz3 @ self.w3.T) * (1.0 - z2 * z2)
            dw2 = z1.T @ dz2; db2 = dz2.sum(axis=0)
            dz1 = (dz2 @ self.w2.T) * (1.0 - z1 * z1)
            dw1 = x0.T @ dz1; db1 = dz1.sum(axis=0)
            self.w3 -= lr * dw3; self.b3 -= lr * db3
            self.w2 -= lr * dw2; self.b2 -= lr * db2
            self.w1 -= lr * dw1; self.b1 -= lr * db1
        self.loss = float(np.mean((self.forward(x)[0] - target) ** 2))
        if validation_samples:
            vx = np.vstack([s[0] for s in validation_samples])
            vy = np.vstack([s[1] for s in validation_samples])
            self.validation_loss = float(np.mean((self.forward(vx)[0] - vy) ** 2))

    def gains(self, ctx):
        # Fall back to the interpretable fuzzy scheduler outside the training
        # envelope instead of extrapolating an unconstrained neural surface.
        if not (-100.0 <= ctx['speed'] <= 1300.0 and
                -1100.0 <= ctx['previous_error'] <= 1100.0 and
                -2.0 <= ctx['integral'] <= 2.0):
            return fuzzy_gains(ctx)
        x = self.features(ctx['ref'], ctx['speed'], ctx['previous_error'], ctx['integral'])
        y, _ = self.forward(x)
        kp = KP_LO + (float(y[0, 0]) + 1.0) * 0.5 * (KP_HI - KP_LO)
        ki = KI_LO + (float(y[0, 1]) + 1.0) * 0.5 * (KI_HI - KI_LO)
        return clip(kp, KP_LO, KP_HI), clip(ki, KI_LO, KI_HI)


def train_nn():
    rng = np.random.default_rng(17)
    samples = []
    for _ in range(6000):
        ref = float(rng.choice(SPEED_REFS))
        speed = float(rng.uniform(-100, 1300))
        prev = float(rng.uniform(-1100, 1100))
        integral = float(rng.uniform(-2, 2))
        ctx = {'ref': ref, 'speed': speed, 'previous_error': prev, 'integral': integral}
        kp, ki = fuzzy_gains(ctx)
        target = np.array([[2 * (kp - KP_LO) / (KP_HI - KP_LO) - 1,
                            2 * (ki - KI_LO) / (KI_HI - KI_LO) - 1]])
        samples.append((NnPid.features(ref, speed, prev, integral), target))
    split = int(0.8 * len(samples))
    model = NnPid()
    model.fit(samples[:split], validation_samples=samples[split:])
    return model


def simulate(seed, ref, policy):
    inertia = 1.0 + 0.08 * (seed % 5)
    load = 35.0 + 6.0 * (seed % 7)
    ctx = {'ref': ref, 'speed': 0.0, 'integral': 0.0,
           'previous_error': 0.0, 'kp': KP_BASE, 'ki': KI_BASE}
    errors, currents = [], []
    overshoot = 0.0
    for _ in range(WINDOWS):
        kp, ki = policy(ctx)
        ctx['kp'], ctx['ki'] = clip(kp, KP_LO, KP_HI), clip(ki, KI_LO, KI_HI)
        for _ in range(INNER_STEPS):
            error = ref - ctx['speed']
            ctx['integral'] = clip(ctx['integral'] + DT * ctx['ki'] * error, -2.0, 2.0)
            current = clip(ctx['kp'] * error + ctx['integral'], -3.0, 3.0)
            acceleration = (1400.0 * current - 0.8 * ctx['speed'] - load) / inertia
            ctx['speed'] += DT * acceleration
            ctx['previous_error'] = error
            errors.append(error / 1000.0)
            currents.append(current)
            overshoot = max(overshoot, max(0.0, ctx['speed'] - ref))
    current_mse = float(np.mean((np.asarray(currents) / 4.0) ** 2))
    peak = float(np.max(np.abs(currents)))
    saturation = float(np.mean(np.abs(currents) >= 0.99 * 3.0))
    rmse = float(np.sqrt(np.mean(np.asarray(errors) ** 2)))
    reward = (-rmse * rmse - 0.05 * current_mse - 0.012 * (peak / 4.0) ** 2
              - 0.04 * saturation - 0.02 * (overshoot / 1000.0) ** 2)
    return {'seed': seed, 'speed_ref_rpm': ref, 'reward': reward,
            'rmse_normalized': rmse, 'peak_current_a': peak,
            'overshoot_rpm': overshoot, 'saturation_fraction': saturation,
            'fault_count': 0}


def objective(rows):
    return float(np.mean([r['rmse_normalized'] ** 2
                          + 0.05 * (r['peak_current_a'] / 4) ** 2
                          + 0.02 * (r['overshoot_rpm'] / 1000.0) ** 2
                          + 0.04 * r['saturation_fraction']
                          + 0.25 * r['fault_count'] for r in rows]))


def _candidate_is_safe(rows):
    return all(row['fault_count'] == 0 and
               row['peak_current_a'] <= MAX_PEAK_CURRENT and
               row['overshoot_rpm'] <= MAX_OVERSHOOT_RPM for row in rows)


def tune_skill():
    """Use safe coarse-to-fine bounded search instead of one giant grid."""
    best = None
    evaluated = 0
    safe_candidates = 0
    ranges = [(KP_LO, KP_HI, KI_LO, KI_HI, 5)]
    for kp_lo, kp_hi, ki_lo, ki_hi, count in ranges:
        for kp in np.linspace(kp_lo, kp_hi, count):
            for ki in np.linspace(ki_lo, ki_hi, count):
                rows = [simulate(seed, ref, fixed_policy(kp, ki))
                        for seed in TRAIN_SEEDS for ref in SPEED_REFS]
                evaluated += 1
                if not _candidate_is_safe(rows):
                    continue
                safe_candidates += 1
                score = objective(rows)
                if best is None or score < best['score']:
                    best = {'kp': float(kp), 'ki': float(ki), 'score': score}
    if best is None:
        raise RuntimeError('No safe AI-skill candidate in the bounded search region')
    # Refine only around the safe coarse winner; this keeps the search bounded
    # and makes every tested candidate auditable.
    kp_step = (KP_HI - KP_LO) / 4.0
    ki_step = (KI_HI - KI_LO) / 4.0
    for kp in np.linspace(max(KP_LO, best['kp'] - kp_step), min(KP_HI, best['kp'] + kp_step), 5):
        for ki in np.linspace(max(KI_LO, best['ki'] - ki_step), min(KI_HI, best['ki'] + ki_step), 5):
            rows = [simulate(seed, ref, fixed_policy(kp, ki))
                    for seed in TRAIN_SEEDS for ref in SPEED_REFS]
            evaluated += 1
            if not _candidate_is_safe(rows):
                continue
            safe_candidates += 1
            score = objective(rows)
            if score < best['score']:
                best.update(kp=float(kp), ki=float(ki), score=score)
    best['candidates_evaluated'] = evaluated
    best['safe_candidates'] = safe_candidates
    return best


def aggregate(name, rows, extra=None):
    result = {'method': name, 'fixtures': rows,
              'mean_reward': float(np.mean([r['reward'] for r in rows])),
              'mean_rmse_normalized': float(np.mean([r['rmse_normalized'] for r in rows])),
              'mean_peak_current_a': float(np.mean([r['peak_current_a'] for r in rows])),
              'max_peak_current_a': float(np.max([r['peak_current_a'] for r in rows])),
              'mean_overshoot_rpm': float(np.mean([r['overshoot_rpm'] for r in rows])),
              'mean_saturation_fraction': float(np.mean([r['saturation_fraction'] for r in rows])),
              'fault_count': int(sum(r['fault_count'] for r in rows))}
    if extra:
        result.update(extra)
    return result


def load_td3(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not data.get('simulation_only', False):
        raise ValueError('TD3 comparison input must be marked simulation_only')
    if data.get('exploration_enabled', False):
        raise ValueError('TD3 comparison input must be a fixed-policy evaluation')
    rows = []
    for row in data['fixtures']:
        if row['policy'] == 'baseline':
            continue
        rows.append({'seed': row['seed'], 'speed_ref_rpm': SPEED_REFS[len(rows)],
                     'reward': row['reward'], 'rmse_normalized': row['rmse_normalized'],
                     'peak_current_a': row['peak_current_a'],
                     'overshoot_rpm': row['overshoot_rpm'],
                     'saturation_fraction': row['saturation_fraction'],
                     'fault_count': row['fault_count']})
    if len(rows) != 3:
        raise ValueError('TD3 evaluation must contain three candidate fixtures')
    if not _candidate_is_safe(rows):
        raise ValueError('TD3 candidate fails the comparison safety gate')
    return rows, data


def write_markdown(path, report):
    methods = report['methods']
    lines = ['# Controller comparison (simulation only)', '',
             '| Method | Mean RMSE | Mean peak current (A) | Mean overshoot (rpm) | Saturation | Faults |',
             '|---|---:|---:|---:|---:|---:|']
    for m in methods:
        lines.append('| {method} | {mean_rmse_normalized:.6f} | {mean_peak_current_a:.4f} | '
                     '{mean_overshoot_rpm:.3f} | {mean_saturation_fraction:.4f} | {fault_count} |'.format(**m))
    lines += ['', '## Interpretation', '',
              '- All methods use the same deterministic mock plant, references, and test seeds.',
              '- The TD3 rows come from the MATLAB TD3 evaluation report supplied to the experiment.',
              '- The NN-PID is supervised to imitate the fuzzy gain schedule; it is not TD3.',
              '- The bounded AI skill row is a safe candidate search, not a neural policy.',
              '- These numbers do not authorize real-motor deployment or prove hardware performance.', '']
    path.write_text('\n'.join(lines), encoding='utf-8')


def run(args):
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new and empty')
    output.mkdir(parents=True, exist_ok=True)
    skill = tune_skill()
    nn = train_nn()
    baseline_rows = [simulate(seed, ref, fixed_policy(KP_BASE, KI_BASE))
                     for seed, ref in zip(TEST_SEEDS, SPEED_REFS)]
    skill_rows = [simulate(seed, ref, fixed_policy(skill['kp'], skill['ki']))
                  for seed, ref in zip(TEST_SEEDS, SPEED_REFS)]
    fuzzy_rows = [simulate(seed, ref, fuzzy_gains) for seed, ref in zip(TEST_SEEDS, SPEED_REFS)]
    nn_rows = [simulate(seed, ref, nn.gains) for seed, ref in zip(TEST_SEEDS, SPEED_REFS)]
    td3_rows, td3_source = load_td3(args.td3_evaluation)
    methods = [
        aggregate('fixed PI baseline', baseline_rows),
        aggregate('AI skill bounded search', skill_rows, {'selected_kp': skill['kp'], 'selected_ki': skill['ki'],
                                                          'candidate_count': skill['candidates_evaluated'],
                                                          'safe_candidate_count': skill['safe_candidates']}),
        aggregate('fuzzy PID', fuzzy_rows),
        aggregate('neural-network PID', nn_rows, {'supervised_target': 'fuzzy PID',
                                                  'training_loss': nn.loss,
                                                  'validation_loss': nn.validation_loss}),
        aggregate('TD3 Actor', td3_rows, {'td3_source': 'MATLAB TD3', 'td3_simulation_only': td3_source.get('simulation_only', True)})]
    baseline_rmse = methods[0]['mean_rmse_normalized']
    for m in methods:
        m['rmse_change_vs_baseline_pct'] = 100.0 * (m['mean_rmse_normalized'] / baseline_rmse - 1.0)
    report = {'schema_version': 2, 'simulation_only': True,
              'plant': 'motor_runtime.MockDevice-compatible deterministic speed PI plant',
              'speed_refs_rpm': list(SPEED_REFS), 'test_seeds': list(TEST_SEEDS),
              'training_seeds_for_skill_and_nn': list(TRAIN_SEEDS),
              'improvements': {
                  'ai_skill': 'coarse-to-fine bounded search with multi-objective safety gate',
                  'fuzzy_pid': '7x7 triangular/trapezoidal memberships with weighted-centroid defuzzification',
                  'neural_network_pid': 'supervised fuzzy-schedule imitation with validation split and OOD fallback',
                  'td3_actor': 'simulation-only source gate; external TD3 report must pass safety metrics'},
              'methods': methods, 'td3_evaluation_source': str(Path(args.td3_evaluation).name),
              'td3_training_note': 'MATLAB TD3 candidate is from a 20-round, 600-experience mock run; no hardware access.',
              'winner_by_rmse': min(methods, key=lambda x: x['mean_rmse_normalized'])['method'],
              'deployment_approved': False}
    (output / 'comparison-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    with (output / 'comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ['method', 'mean_rmse_normalized', 'rmse_change_vs_baseline_pct',
                  'mean_peak_current_a', 'max_peak_current_a', 'mean_overshoot_rpm',
                  'mean_saturation_fraction', 'fault_count']
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in methods: writer.writerow({k: row[k] for k in fields})
    write_markdown(output / 'comparison.md', report)
    print(json.dumps({'output': str(output), 'winner_by_rmse': report['winner_by_rmse'],
                      'methods': [{k: m[k] for k in ('method', 'mean_rmse_normalized',
                                                     'mean_peak_current_a', 'fault_count')}
                                  for m in methods]}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--td3-evaluation', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run(args)
