"""Scope and real-ACK schedule checks; never contact a device."""
import argparse,json,unittest
from pathlib import Path
from types import SimpleNamespace
import speedloop_reference_plus4_hold as runtime

ROOT=None
class Checks(unittest.TestCase):
    def args(self):
        path=ROOT/(self._testMethodName+'.json');path.write_text(json.dumps(runtime.expected_schedule(0)))
        return SimpleNamespace(phase='prepare',authorized_reference_upper8_capture=True,gain_mode='kp_probe',
            build=r'E:\dianji\motor-td3-local-results\reference-v26-review-20261014\firmware-v26',
            adapter_checks=r'E:\dianji\motor-td3-local-results\reference-v26-review-20261014\adapter-checks\reference-v26-summary.json',
            output=str(ROOT/(self._testMethodName+'-out')),schedule_index=0,schedule_contract=str(path),
            previous_trial_summary=r'E:\dianji\motor-td3-local-results\reference-joint-support-20261014\round1\trial\summary.json')
    def test_exact_image_and_restored_globals(self):
        patterns=runtime.base.PATTERNS;version=runtime.base.VERSION
        self.assertEqual(runtime.validate(self.args())['build_id'],runtime.IDENTITY)
        self.assertEqual(runtime.base.PATTERNS,patterns);self.assertEqual(runtime.base.VERSION,version)
    def test_actual_readback_schedule_never_exceeds_plus4(self):
        for pattern in runtime.PATTERNS:
            p=runtime.base.ReferenceProbe(pattern)
            for ms in range(0,23800,50):
                kp,ki=p.planned(ms);self.assertEqual(ki,runtime.KI)
                self.assertIn(kp,(runtime.LEVELS[0],runtime.LEVELS[4]))
                self.assertLessEqual(abs(kp-p.actual),.00013556+1e-9)
                p.observe(dict(kp=kp,ki=ki))
                self.assertEqual(kp,runtime.LEVELS[4] if 6750<=ms<21750 else runtime.LEVELS[0])
    def test_budget_ki_and_pattern_changes_rejected(self):
        a=self.args()
        for k,v in [('fixed_ki',.0015),('reserved_motion_seconds',25),('pattern',[0]*32),
                    ('whole_boot_role','validation'),('maximum_commanded_kp',runtime.LEVELS[8])]:
            c=runtime.expected_schedule(0);c[k]=v;Path(a.schedule_contract).write_text(json.dumps(c))
            with self.assertRaises(ValueError):runtime.validate(a)
    def test_no_flash_actor_or_ki_mode(self):
        for phase in ('flash','qualify','resume'):
            with self.assertRaises(ValueError):runtime.validate(SimpleNamespace(phase=phase))
        for k,v in [('apply_shadow_kp',True),('ki_probe_sign',1),('gain_mode','baseline')]:
            a=self.args();setattr(a,k,v)
            with self.assertRaises(ValueError):runtime.validate(a)
    def test_missed_first_slot_and_unknown_ACK_rejected(self):
        p=runtime.base.ReferenceProbe(runtime.PATTERNS[0])
        with self.assertRaises(RuntimeError):p.planned(6800)
        p.planned(6250)
        with self.assertRaises(RuntimeError):p.observe(dict(kp=.0036,ki=runtime.KI))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();ROOT=Path(a.output)
    assert Path('E:/simulink/_codex_tmp').resolve() in ROOT.resolve().parents;ROOT.mkdir(exist_ok=False)
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (ROOT/'summary.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,
        hardware_accessed=False,motion_started=False,Actor_applied=False))+'\n')
    raise SystemExit(0 if r.wasSuccessful() else 1)
