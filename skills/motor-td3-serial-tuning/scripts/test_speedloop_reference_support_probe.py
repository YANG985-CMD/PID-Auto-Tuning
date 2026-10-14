"""Bounded host schedule checks; no CAN/MCU imports or access."""
import argparse,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_reference_support_probe as runtime

ROOT=None

class Checks(unittest.TestCase):
    def args(self):
        cfg=ROOT/'fixture-contract.json';cfg.write_text(json.dumps(runtime.expected_schedule(0)))
        return SimpleNamespace(phase='prepare',authorized_reference_upper8_capture=True,gain_mode='kp_probe',
            build=r'E:\dianji\motor-td3-local-results\reference-v26-review-20261014\firmware-v26',
            adapter_checks=r'E:\dianji\motor-td3-local-results\reference-v26-review-20261014\adapter-checks\reference-v26-summary.json',
            output=str(ROOT/(self._testMethodName+'-out')),schedule_index=0,schedule_contract=str(cfg),
            previous_trial_summary=r'E:\dianji\motor-td3-local-results\reference-v26-capture-20261014\dynamic-round1\trial\summary.json')

    def test_exact_existing_image_prepare(self):
        self.assertEqual(runtime.validate(self.args())['build_id'],runtime.IDENTITY)

    def test_patterns_feasible_actual_ack_and_reference_coverage(self):
        required={(r,l) for r in (950,1000,1050) for l in (0,2,4,6,8)}
        for index,pattern in enumerate(runtime.PATTERNS):
            self.assertEqual(len(pattern),32);self.assertEqual(pattern[0],0);self.assertEqual(pattern[-1],0)
            planned={(runtime.base.reference_rpm((6250+500*k)*1000),level)
                for k,level in enumerate(pattern)}
            self.assertTrue(planned<=required)
            self.assertEqual(planned,{tuple(x) for x in runtime.expected_schedule(index)['planned_reference_target_categories']})
            self.assertTrue(all(abs(a-b)<=4 for a,b in zip(pattern,pattern[1:])))
            probe=runtime.base.ReferenceProbe(pattern)
            for ms in range(3900,23800,50):
                kp,ki=probe.planned(ms);self.assertEqual(ki,runtime.KI)
                self.assertLessEqual(abs(kp-probe.actual),.00013556+1e-9)
                probe.observe(dict(kp=kp,ki=ki))
                target=pattern[(ms-6250)//500] if 6250<=ms<22250 else 0
                self.assertEqual(kp,runtime.LEVELS[target])

    def test_no_other_phase_or_actor(self):
        for phase in ('flash','qualify','resume'):
            with self.assertRaises(ValueError):runtime.validate(SimpleNamespace(phase=phase))
        a=self.args();a.apply_shadow_kp=True
        with self.assertRaises(ValueError):runtime.validate(a)

    def test_mutated_pattern_scope_or_budget_rejected(self):
        a=self.args()
        for k,v in [('pattern',list(runtime.base.PATTERNS[0])),('maximum_batch_motion_seconds',72),
                    ('fixed_ki',.0015),('whole_boot_role','validation'),('design_replay_summary_sha256','0'*64)]:
            cfg=runtime.expected_schedule(0);cfg[k]=v;Path(a.schedule_contract).write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):runtime.validate(a)

    def test_dispatch_restores_base_globals(self):
        a=self.args();original_pattern=runtime.base.PATTERNS;original_version=runtime.base.VERSION
        def inspect(args):
            self.assertEqual(runtime.base.PATTERNS,runtime.PATTERNS)
            self.assertEqual(runtime.base.expected_schedule(0),runtime.expected_schedule(0))
            Path(args.output).mkdir();return dict(passed=True,hardware_accessed=False,fixture_only=True)
        with patch.object(runtime.base,'run',inspect):runtime.run(a)
        self.assertEqual(runtime.base.PATTERNS,original_pattern);self.assertEqual(runtime.base.VERSION,original_version)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();ROOT=Path(a.output)
    assert Path('E:/simulink/_codex_tmp').resolve() in ROOT.resolve().parents;ROOT.mkdir(exist_ok=False)
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (ROOT/'summary.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,
        hardware_accessed=False,motion_started=False,deployment_allowed=False))+'\n')
    raise SystemExit(0 if r.wasSuccessful() else 1)
