import unittest
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_binary_probe as probe
import speedloop_excitation_review as old


class Checks(unittest.TestCase):
    def test_all_slots_inside_verified_actions(self):
        for index in range(3):
            self.assertEqual(sum(probe.PATTERNS[index]),6)
            for t in range(0,8001):
                kp,ki=probe.planned_gains(t,index=index)
                self.assertIn(kp,[probe.f32(.003389),probe.f32(.00352456)])
                self.assertEqual(ki,probe.f32(.00144))
                if t<3900 or t>=6900:self.assertEqual(kp,probe.f32(.003389))

    def test_scope_and_actor_reject_before_access(self):
        with self.assertRaises(ValueError):probe.run(SimpleNamespace(authorized_binary_probe=False))
        args=SimpleNamespace(authorized_binary_probe=True,probe_schedule_index=0,
            build='E:/simulink/_codex_tmp/td3-excitation-evidence-20261012/build-8s',
            apply_shadow_kp=True)
        with self.assertRaises(ValueError):probe.run(args)

    def test_old_schedule_restored_after_failure(self):
        before=old.planned_gains
        args=SimpleNamespace(authorized_binary_probe=True,probe_schedule_index=0,phase='trial',
            build='E:/simulink/_codex_tmp/td3-excitation-evidence-20261012/build-8s')
        with patch.object(probe.review,'run',side_effect=RuntimeError('synthetic stop')):
            with self.assertRaises(RuntimeError):probe.run(args)
        self.assertIs(old.planned_gains,before)


if __name__=='__main__':unittest.main()
