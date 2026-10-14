import unittest
from types import SimpleNamespace
import speedloop_handover_review as startup
import speedloop_handover_excitation as excitation
import speedloop_startup_review as old_startup
import speedloop_excitation_review as old_excitation

class Checks(unittest.TestCase):
    def test_scopes_before_access(self):
        for entry,key in ((startup,'authorized_handover_review'),(excitation,'authorized_handover_excitation')):
            with self.assertRaises(ValueError):entry.run(SimpleNamespace(**{key:False}))

    def test_bad_action_restores_exact_entry_after_rejection(self):
        rows=((startup,old_startup,'authorized_handover_review','E:/simulink/_codex_tmp/td3-handover-review-20261012/build-final'),
              (excitation,old_excitation,'authorized_handover_excitation','E:/simulink/_codex_tmp/td3-handover-excitation-20261012/build-8s'))
        for entry,old,key,build in rows:
            identity,sha=old.IDENTITY,old.IMAGE_SHA
            for bad in ({'gain_mode':'ki_probe'},{'ki_probe_sign':1},{'apply_shadow_kp':True},{'shadow_port':55000}):
                args=SimpleNamespace(build=build,phase='trial',**{key:True},**bad)
                with self.assertRaises(ValueError):entry.run(args)
                self.assertEqual((old.IDENTITY,old.IMAGE_SHA),(identity,sha))

if __name__=='__main__':unittest.main()
