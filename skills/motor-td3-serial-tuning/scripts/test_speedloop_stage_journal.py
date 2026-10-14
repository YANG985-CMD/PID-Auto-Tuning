"""Synthetic journal fault cases only; never connected to a board or trainer."""
import tempfile
from pathlib import Path
import unittest
from speedloop_stage_journal import StageJournal, PAIRS

ROOT = Path('E:/simulink/_codex_tmp/td3-ki-warm-20261013/journal-tests')


class StageJournalTest(unittest.TestCase):
    def fixture(self, missing=False, wrong=False):
        ROOT.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix='synthetic-', dir=ROOT)
        self.addCleanup(scratch.cleanup)
        folder = Path(scratch.name).resolve()
        self.assertIn(ROOT.resolve(), folder.parents)
        j = StageJournal(folder/'journal')
        kp,ki = PAIRS[0]
        source = dict(boot_id='synthetic', seq=1, t_us=3880000, elapsed_ms=3880,
            enabled=True, fault=0, kp=kp, ki=ki, applied_seq=0, t_apply_us=0)
        j._offer(dict(kind='telemetry', packet=source, stage_proof=None))
        command = dict(type='gains', command_seq=1, source_t_us=source['t_us'],
            expires_us=3980000, kp=kp, ki=ki if not wrong else .002)
        j.command(command, source)
        packet = dict(source, seq=2, t_us=3900000, elapsed_ms=3900,
            applied_seq=1, t_apply_us=3890000)
        proof = dict(started=1, run_seen=1, fault=0, irq_fault=0, started_us=0,
            run_started_us=2200000, last_us=3901000)
        j._offer(dict(kind='telemetry', packet=packet, stage_proof=None if missing else proof))
        return j.close()

    def test_valid_journal_without_training(self):
        r = self.fixture()
        self.assertTrue(r['closed'])
        self.assertIsNone(r['error'])
        self.assertEqual(r['actual_stage_proofs'],1)
        self.assertFalse(r['training_performed'])

    def test_missing_actual_proof_rejected(self):
        self.assertIn('stage proof missing',self.fixture(missing=True)['error'])

    def test_unreviewed_action_rejected(self):
        self.assertIn('Unknown or unordered',self.fixture(wrong=True)['error'])


if __name__=='__main__':
    unittest.main()
