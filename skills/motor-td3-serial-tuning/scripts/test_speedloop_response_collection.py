"""Fault, order and consumed-budget checks with no hardware imports/calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import collect_speedloop_response as collect


class Checks(unittest.TestCase):
    def exercise(self,root,order='probe-first',fault=0):
        calls=[]
        def fake(cmd,**unused):
            calls.append(cmd)
            out=Path(cmd[cmd.index('--output')+1]);out.mkdir(parents=True)
            phase=cmd[3]
            obj=dict(passed=True)
            if phase=='trial':
                obj.update(trial_timing=dict(last_us=7800000,started_us=0),
                    final_irq_fault=fault,final_tx_fault=0,protocol_stop_acknowledged=True,
                    core_halted_after_physical_shutdown=True,can_released_after_shutdown=True,
                    complete_telemetry_packets=398)
            (out/'summary.json').write_text(json.dumps(obj),encoding='utf-8')
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        args=SimpleNamespace(build='unused',nm='unused',output=str(root/'batch'),order=order,
            power_confirmed=True,authorized_no_thermal_trial=True)
        with patch.object(collect.review,'validate'),patch.object(collect.subprocess,'run',side_effect=fake),patch.object(collect.time,'sleep') as sleep:
            r=collect.run(args)
        return r,calls,sleep,args

    def test_reverse_order_and_fixed_budget(self):
        with tempfile.TemporaryDirectory(dir='E:/simulink/_codex_tmp') as folder:
            r,calls,sleep,args=self.exercise(Path(folder))
            self.assertTrue(r['passed']);self.assertEqual(r['reserved_batch_motion_seconds'],16)
            self.assertEqual([c[c.index('--gain-mode')+1] for c in calls],['kp_probe','kp_probe','baseline','baseline'])
            sleep.assert_called_once_with(30)
            with patch.object(collect.review,'validate'),patch.object(collect.subprocess,'run') as live:
                with self.assertRaises(FileExistsError):collect.run(args)
                live.assert_not_called()

    def test_latched_fault_stops_the_pair(self):
        with tempfile.TemporaryDirectory(dir='E:/simulink/_codex_tmp') as folder:
            r,calls,sleep,_=self.exercise(Path(folder),fault=8)
            self.assertFalse(r['passed']);self.assertEqual(len(calls),2);sleep.assert_not_called()

    def test_invalid_order_rejected_before_create_or_hardware(self):
        with tempfile.TemporaryDirectory(dir='E:/simulink/_codex_tmp') as folder:
            args=SimpleNamespace(output=str(Path(folder)/'batch'),power_confirmed=True,
                authorized_no_thermal_trial=True,order='unbounded')
            with patch.object(collect.review,'validate'),patch.object(collect.subprocess,'run') as live:
                with self.assertRaises(ValueError):collect.run(args)
                live.assert_not_called()


if __name__=='__main__':unittest.main()
