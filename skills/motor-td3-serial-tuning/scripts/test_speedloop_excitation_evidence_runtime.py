"""Reject changed scope, images or actions before hardware access."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import speedloop_excitation_evidence as entry
import speedloop_handover_excitation as old
import speedloop_excitation_review as base

BUILD='E:/simulink/_codex_tmp/td3-excitation-evidence-20261012/build-8s'


class Checks(unittest.TestCase):
    def test_no_scope(self):
        with self.assertRaises(ValueError):entry.run(SimpleNamespace(authorized_excitation_evidence=False))

    def test_wrong_identity(self):
        a=SimpleNamespace(build='E:/simulink/_codex_tmp/td3-handover-excitation-20261012/build-8s',
                          authorized_excitation_evidence=True)
        with self.assertRaises(ValueError):entry.validate(a)

    def test_bad_actions_restore_older_entries(self):
        before=(base.IDENTITY,base.IMAGE_SHA,base.HALL_TRACE_CAPACITY,old.IDENTITY,old.IMAGE_SHA)
        for bad in ({'gain_mode':'ki_probe'},{'ki_probe_sign':1},
                    {'apply_shadow_kp':True},{'shadow_port':55000}):
            a=SimpleNamespace(build=BUILD,phase='trial',authorized_excitation_evidence=True,**bad)
            with self.assertRaises(ValueError):entry.run(a)
            self.assertEqual(before,(base.IDENTITY,base.IMAGE_SHA,base.HALL_TRACE_CAPACITY,old.IDENTITY,old.IMAGE_SHA))

    def test_valid_file_gate_only(self):
        r=entry.validate(SimpleNamespace(build=BUILD,authorized_excitation_evidence=True,gain_mode='baseline'))
        self.assertEqual(r['hall_trace_capacity'],832)


if __name__=='__main__':unittest.main()
