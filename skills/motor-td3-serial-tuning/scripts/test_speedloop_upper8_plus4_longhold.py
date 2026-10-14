import copy,json,os,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import speedloop_upper8_plus4_longhold as runtime

class Checks(unittest.TestCase):
    def test_plans_actual_ack_and_return(self):
        with runtime.context():
            p=runtime.previous
            self.assertEqual(p.PATTERNS,((0,4),(4,0)))
            self.assertEqual(p.ANALYSIS_SETTLE_MS,7000)
            for pattern in p.PATTERNS:
                probe=p.ContinuousUpperProbe(pattern)
                for ms in range(3900,23300,50):
                    kp,ki=probe.planned(ms)
                    self.assertLessEqual(abs(kp-probe.actual),p.HOST_STEP+1e-9)
                    self.assertEqual(ki,p.KI);probe.observe(dict(kp=kp,ki=ki))
                    if 4100<=ms<13000:self.assertEqual(kp,p.LEVELS[pattern[0]])
                    if 13100<=ms<22000:self.assertEqual(kp,p.LEVELS[pattern[1]])
                    if ms>=22100:self.assertEqual(kp,p.LEVELS[0])
        self.assertEqual(runtime.previous.PLATEAU_MS,4500)
    def test_recovery_evidence_and_mutations_rejected(self):
        root=Path(os.environ['MOTOR_TD3_TEST_ROOT'])/'recovery-fixture';root.mkdir(parents=True,exist_ok=True)
        state=json.loads(Path(os.environ['MOTOR_TD3_RECOVERY_STATE']).read_text())
        cfg=dict(hold_design=runtime.VERSION,gain_hold_seconds=9,post_actual_apply_wait_seconds=7,
            physical_behavior_probe_not_frozen_actor=True,probe_mode='upper8-continuous-plus4-longhold',
            independent_performance_evaluation=True,fresh_human_fault_recovery_authorization=True)
        for change in (None,'core_halted','irq_fault','tx_fault','hardware_written','phase','authorization'):
            with self.subTest(change=change):
                value=copy.deepcopy(state);contract=copy.deepcopy(cfg)
                if change=='core_halted':value[change]=False
                if change=='irq_fault':value[change]=0
                if change=='tx_fault':value[change]=1
                if change=='hardware_written':value[change]=True
                if change=='phase':value['registers']['gpioa_odr']=0x100
                if change=='authorization':contract['fresh_human_fault_recovery_authorization']=False
                path=root/'state.json';path.write_text(json.dumps(value))
                contract['recovery_readonly_sha256']=runtime.hashlib.sha256(path.read_bytes()).hexdigest()
                cpath=root/'contract.json';cpath.write_text(json.dumps(contract))
                args=SimpleNamespace(phase='prepare',schedule_index=0,schedule_contract=str(cpath),
                    recovery_readonly=str(path),fault_recovery_authorized=True)
                with patch.object(runtime.previous,'validate',return_value=True):
                    if change is None:self.assertTrue(runtime.validate(args))
                    else:
                        with self.assertRaises(ValueError):runtime.validate(args)
    def test_no_flash_entry(self):
        with self.assertRaises(ValueError):runtime.validate(SimpleNamespace(phase='flash'))

if __name__=='__main__':unittest.main()
