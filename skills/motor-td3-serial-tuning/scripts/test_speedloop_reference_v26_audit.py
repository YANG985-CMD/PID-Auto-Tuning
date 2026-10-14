"""Reject corrupted real-capture copies without contacting any device."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from audit_speedloop_reference_v26 import audit


def run(source, contract, output):
    source, contract, output = map(Path, (source, contract, output))
    assert Path('E:/simulink/_codex_tmp').resolve() in output.resolve().parents
    output.mkdir(exist_ok=False)

    class Checks(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory(dir=output)
            self.root = Path(self.tmp.name)
            for name in ('trial/summary.json', 'trial/telemetry.jsonl', 'stream/events.jsonl'):
                dst = self.root / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, dst)
            self.contract = self.root / 'contract.json'
            shutil.copy2(contract, self.contract)

        def tearDown(self):
            self.tmp.cleanup()

        def call(self):
            with contextlib.redirect_stdout(io.StringIO()):
                return audit(self.root, self.contract, 0, self.root / 'result.json')

        def corrupt_event(self, predicate, mutation):
            path = self.root / 'stream/events.jsonl'
            rows = [json.loads(s) for s in path.read_text().splitlines()]
            mutation(next(r for r in rows if predicate(r)))
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))

        def test_retained_physical_capture(self):
            self.assertTrue(self.call()['passed'])

        def test_missing_stop_acknowledgement(self):
            path = self.root / 'trial/summary.json'
            r = json.loads(path.read_text())
            r['protocol_stop_acknowledged'] = False
            path.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError, 'stopped trial'):
                self.call()

        def test_reference_is_permitted_but_wrong_clock(self):
            self.corrupt_event(lambda r: r['kind'] == 'telemetry' and 8100 < r['packet']['elapsed_ms'] < 8200,
                lambda r: r['packet'].update(speed_ref=1000))
            with self.assertRaisesRegex(ValueError, 'reference clock'):
                self.call()

        def test_actual_action_readback_corruption(self):
            self.corrupt_event(lambda r: r['kind'] == 'telemetry' and r['packet']['applied_seq'] > 20,
                lambda r: r['packet'].update(ki=.0015))
            with self.assertRaisesRegex(ValueError, 'acknowledgement'):
                self.call()

        def test_command_sequence_gap(self):
            self.corrupt_event(lambda r: r['kind'] == 'command' and r['command']['type'] == 'gains',
                lambda r: r['command'].update(command_seq=2))
            with self.assertRaisesRegex(ValueError, 'sequence gap'):
                self.call()

        def test_post_capture_contract_mutation(self):
            r = json.loads(self.contract.read_text())
            r['whole_boot_role'] = 'validation'
            self.contract.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError, 'predeclared'):
                self.call()

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    report = dict(passed=result.wasSuccessful(), tests=result.testsRun,
        real_data_source=str(source.resolve()), corrupted_copies_removed=True,
        hardware_accessed=False, new_physical_data=False, training_performed=False)
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'contract', 'output'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.source, a.contract, a.output)['passed'] else 1)
