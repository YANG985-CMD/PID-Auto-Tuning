"""Probe malformed contracts and actual-readback bridging without hardware."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_fullhall_probe as subject


class ProbeTest(unittest.TestCase):
    def test_bridge_uses_actual_gain_and_old_single_step(self):
        for pattern in subject.PATTERNS+subject.MIDDLE_PATTERNS:
            with subject.context(pattern):
                policy = subject.previous.StagedProbe()
                for slot, level in enumerate(pattern):
                    for elapsed in (6000 + slot*2000, 6050 + slot*2000):
                        before = policy.actual
                        kp, ki = policy.planned(elapsed)
                        self.assertLessEqual(abs(kp-before), subject.previous.STEP+1e-9)
                        policy.observe(dict(kp=kp, ki=ki, enabled=True, applied_seq=slot+1))
                    self.assertEqual(policy.actual, subject.previous.LEVELS[level])

    def test_middle_mode_is_exact_and_must_be_predeclared(self):
        a=SimpleNamespace(probe_mode='middle',schedule_index=1)
        self.assertEqual(subject.declared_pattern(a,dict(probe_mode='middle')),subject.MIDDLE_PATTERNS[1])
        for cfg in ({},{'probe_mode':'endpoints'},{'probe_mode':'arbitrary'}):
            with self.assertRaises(ValueError):subject.declared_pattern(a,cfg)

    def test_positive_probe_stays_inside_exact_image_domain(self):
        cfg=dict(probe_mode='upper4',action_mapping_redefinition_required=True,
            old_lower16_training_allowed=False)
        for index,pattern in enumerate(subject.PATTERNS):
            a=SimpleNamespace(probe_mode='upper4',schedule_index=index)
            self.assertEqual(subject.declared_pattern(a,cfg),pattern)
            with subject.context(pattern,'upper4'):
                policy=subject.previous.StagedProbe()
                for slot,level in enumerate(pattern):
                    before=policy.actual
                    kp,ki=policy.planned(6000+slot*2000)
                    self.assertLessEqual(abs(kp-before),subject.previous.STEP+1e-9)
                    policy.observe(dict(kp=kp,ki=ki,enabled=True,applied_seq=slot+1))
                    self.assertEqual(kp,subject.UPPER4_LEVELS[level])
                with self.assertRaises(RuntimeError):
                    policy.observe(dict(kp=subject.previous.f32(.003121269),ki=ki))
            for key in ('action_mapping_redefinition_required','old_lower16_training_allowed'):
                wrong=dict(cfg);wrong.pop(key)
                with self.assertRaises(ValueError):subject.declared_pattern(a,wrong)

    def test_switch_schedule_requires_measured_readback_at_every_slot(self):
        cfg=dict(probe_mode='switching-local4',action_mapping_redefinition_required=True,
            old_lower16_training_allowed=False,training_purpose='actual-source-gain-switch-response',
            independent_performance_evaluation=False,actual_switch_interval_ms=500)
        for index,pattern in enumerate(subject.SWITCH_PATTERNS):
            a=SimpleNamespace(probe_mode='switching-local4',schedule_index=index)
            self.assertEqual(subject.declared_pattern(a,cfg),pattern)
            with subject.context(pattern,'switching-local4'):
                policy=subject.previous.StagedProbe();changes=0
                for slot,level in enumerate(pattern):
                    before=policy.actual;kp,ki=policy.planned(6000+500*slot)
                    self.assertLessEqual(abs(kp-before),subject.previous.STEP/2+1e-9)
                    changes+=kp!=before
                    policy.observe(dict(kp=kp,ki=ki,enabled=True,applied_seq=slot+1))
                    self.assertEqual(kp,subject.SWITCH_LEVELS[level])
                kp,ki=policy.planned(22000);changes+=kp!=policy.actual
                self.assertEqual(changes,32);self.assertEqual(kp,subject.SWITCH_LEVELS[0])
                stale=subject.previous.StagedProbe();stale.planned(6000)
                with self.assertRaises(RuntimeError):stale.planned(7000)
            for key in ('training_purpose','independent_performance_evaluation','actual_switch_interval_ms'):
                bad=dict(cfg);bad.pop(key)
                with self.assertRaises(ValueError):subject.declared_pattern(a,bad)

    def test_fault_or_missing_readback_cannot_advance(self):
        with subject.context(subject.PATTERNS[0]):
            policy = subject.previous.StagedProbe()
            policy.planned(6000)
            with self.assertRaises(RuntimeError):
                policy.planned(10000)
            with self.assertRaises(RuntimeError):
                policy.observe(dict(kp=.9, ki=subject.previous.KI))
            with self.assertRaises(ValueError):
                policy.planned(6050, ki_probe_sign=1)

    def test_contract_rejects_before_legacy_validation(self):
        good = dict(live_hall_capture=True,gain_exploration=True,
                    primary_metric_version=subject.METRIC,schedule_index=0,
                    maximum_batch_rounds=2,maximum_batch_motion_seconds=48,
                    minimum_cooldown_seconds=30,deployment_allowed=False,
                    performance_claim_allowed=False)
        with tempfile.TemporaryDirectory(prefix='contract-') as root:
            contract = Path(root)/'contract.json'
            a = SimpleNamespace(phase='prepare', authorized_fullhall_probe=True,
                                schedule_index=0, schedule_contract=str(contract))
            for key, wrong in [('live_hall_capture',False),('primary_metric_version','sparse'),
                               ('maximum_batch_motion_seconds',49),('minimum_cooldown_seconds',29),
                               ('deployment_allowed',True),('schedule_index',1)]:
                cfg = dict(good); cfg[key] = wrong
                contract.write_text(json.dumps(cfg),encoding='utf-8')
                with patch.object(subject.previous, 'validate') as legacy:
                    with self.assertRaises(ValueError): subject.validate(a)
                    legacy.assert_not_called()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output',required=True)
    args = p.parse_args(); out = Path(args.output); out.mkdir(parents=True,exist_ok=False)
    tempfile.tempdir = str(out)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProbeTest))
    (out/'summary.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),
        tests=result.testsRun, hardware_accessed=False))+'\n',encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
