"""One bounded warm-loop Ki response trial; no Actor and no training claim."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import speedloop_motion_gain_trial as trial
import speedloop_continuous as references
from speedloop_duration_review import overrides
from speedloop_lower_commission import IMAGE_SHA as OLD_SHA, IMAGE_BYTES as OLD_BYTES
from build_speedloop_ki_review import IDENTITY

IMAGE_SHA = '8c2a48b4c8d29ef9f445293b985f7750917d457047d54655b2e894b166e946c2'
HEX_SHA = 'd6f068429288001db4c5ce445fd7615b24fea14cc1b463c135237554041843f8'
IMAGE_BYTES = 51156
KI_LEVELS = tuple(map(trial.f32, (.00144, .001404, .001476)))
SEED = 20261019
LEAD_MS = 150


def schedule():
    rng = random.Random(SEED)
    result = []
    # Every cycle contains all Ki points. Across five cycles every reference
    # receives each point, with counts 1/2/2. No current error selects a point.
    shifts = [0, 1, 2, 0, 1]
    rng.shuffle(shifts)
    order = [0, 1, 2]
    rng.shuffle(order)
    for shift in shifts:
        result.extend(order[(phase + shift) % 3] for phase in range(3))
    return tuple(result)


PATTERN = schedule()
BASE_CHECK = trial.check_telemetry


class KiProbe:
    def __init__(self):
        self.segment = -1
        self.decisions = []
    def observe(self, telemetry):
        pass
    def planned(self, elapsed, ki_probe_sign=0, mode='ki_response'):
        if mode != 'ki_response' or ki_probe_sign:
            raise ValueError('Only the declared Ki response schedule is allowed')
        if elapsed < 4000 - LEAD_MS or elapsed >= 22000:
            return trial.f32(.003389), KI_LEVELS[0]
        segment = min(14, int((elapsed + LEAD_MS - 4000) // 1200))
        if segment < self.segment or self.segment >= 0 and segment > self.segment + 1:
            raise RuntimeError('Missed declared Ki segment')
        if segment > self.segment:
            self.segment = segment
            self.decisions.append(dict(segment=segment, source_elapsed_ms=elapsed,
                level=PATTERN[segment], kp=trial.f32(.003389), ki=KI_LEVELS[PATTERN[segment]]))
        return trial.f32(.003389), KI_LEVELS[PATTERN[segment]]


def validate(args):
    if not getattr(args, 'authorized_ki_response', False):
        raise ValueError('Human authorization for continued bounded Kp/Ki exploration is required')
    build = Path(args.build)
    summary = json.loads((build / 'summary.json').read_text(encoding='utf-8'))
    review = summary.get('ki_response_review', {})
    if (not summary['passed'] or summary['build_id'] != IDENTITY
            or summary['bin_sha256'] != IMAGE_SHA or summary['binary_bytes'] != IMAGE_BYTES
            or hashlib.sha256((build / 'speedloop-pi-review.bin').read_bytes()).hexdigest() != IMAGE_SHA
            or hashlib.sha256((build / 'speedloop-pi-review.hex').read_bytes()).hexdigest() != HEX_SHA
            or review.get('exact_ki_levels') != [.001404, .00144, .001476]
            or review.get('fixed_kp') != .003389 or review.get('maximum_motion_seconds') != 24
            or review.get('current_speed_bus_duration_lease_limits_modified') is not False
            or review.get('actor_allowed') is not False or review.get('thermal_gate_modified') is not False):
        raise ValueError('Unexpected image or changed protection/parameter contract')
    if args.phase == 'trial':
        if Path(args.output).exists():
            raise ValueError('Consumed trial cannot be retried')
        c = json.loads(Path(args.schedule_contract).read_text(encoding='utf-8'))
        if (c.get('pattern') != list(PATTERN) or c.get('seed') != SEED
                or c.get('reserved_motion_seconds') != 24 or c.get('requested_rounds') != 1
                or c.get('exact_ki_levels') != list(KI_LEVELS) or c.get('fixed_kp') != trial.f32(.003389)
                or c.get('actor_applied') is not False or c.get('fault_automatic_retry') is not False
                or c.get('reference_position_evaluation_ms') != [[100, 260], [500, 660], [900, 1000]]
                or c.get('verified_cooldown_seconds', 0) < 30):
            raise ValueError('Missing finite predeclared Ki schedule or cooldown')
    return summary


def run(args):
    validate(args)
    if args.phase == 'flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash, IDENTITY=IDENTITY, ENERGIZED_IMAGE_SHA=IMAGE_SHA, OLD_SHA=OLD_SHA, OLD_BYTES=OLD_BYTES):
            return flash.flash(args)
    if args.phase == 'prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare, IDENTITY=IDENTITY, ENERGIZED_IMAGE_SHA=IMAGE_SHA):
            return prepare.prepare(args)
    policy = KiProbe()
    def checked(packet, last, sent):
        BASE_CHECK(packet, last, sent)
        if packet['enabled'] and not references.reference_matches(packet['elapsed_ms'], packet['speed_ref']):
            raise RuntimeError('Different actual reference')
    args.gain_mode = 'ki_response'
    args.ki_probe_sign = 0
    journal = None
    if getattr(args, 'stage_journal', None):
        from speedloop_stage_journal import StageJournal
        journal = StageJournal(args.stage_journal)
        args.runtime_observer = journal
    try:
        with overrides(trial, IDENTITY=IDENTITY, ENERGIZED_IMAGE_SHA=IMAGE_SHA,
            STOP_SECONDS=23.8, GAIN_CUTOFF_SECONDS=23.7, FINAL_GAIN_SECONDS=23.72,
            FINAL_GAIN_DEADLINE_SECONDS=23.75, MAX_MOTION_SECONDS=24, CAPTURE_SECONDS=26,
            TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing', HALL_TRACE_CAPACITY=832,
            planned_gains=policy.planned, check_telemetry=checked):
            result = trial.trial(args)
    finally:
        if journal:
            journal_result = journal.close()
    result.update(actor_applied=False, fixed_kp=trial.f32(.003389), baseline_ki=trial.f32(.00144),
        ki_candidates=list(KI_LEVELS), probe_pattern=list(PATTERN), probe_seed=SEED,
        probe_decisions=policy.decisions, warm_loop_ki_response_capture=True,
        schedule_contract_sha256=hashlib.sha256(Path(args.schedule_contract).read_bytes()).hexdigest(),
        deployment_allowed=False, performance_claim_allowed=False, temperature_gate_modified=False,
        ki_data_added_to_existing_kp_only_replay=False)
    if journal:
        result['stage_journal'] = journal_result
        if journal_result['error'] or not journal_result['closed']:
            result['passed'] = False
    (Path(args.output) / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('flash', 'prepare', 'trial'))
    for name in ('build', 'output'):
        parser.add_argument('--' + name, required=True)
    for name in ('nm', 'pyocd', 'pack', 'boot-token-file', 'schedule-contract', 'stage-journal'):
        parser.add_argument('--' + name)
    parser.add_argument('--uid', default='0674FF554850715087183841')
    for name in ('authorized-ki-response', 'energized-update-authorized', 'power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed', 'power-confirmed', 'authorized-no-thermal-trial'):
        parser.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    needed = {'flash': ('pyocd', 'pack'), 'prepare': ('nm',), 'trial': ('nm', 'boot_token_file', 'schedule_contract')}
    if any(not getattr(args, name) for name in needed[args.phase]):
        parser.error('Missing phase paths')
    raise SystemExit(0 if run(args)['passed'] else 1)
