"""Software scope/clock/ACK checks for v26; no hardware library invoked."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
import speedloop_lower31_v28 as runtime

ROOT=None
BUILD=Path(r'E:\dianji\motor-td3-local-results\lower31-v28-review-20261014\firmware-v28')
CHECKS=Path(r'E:\dianji\motor-td3-local-results\lower31-v28-review-20261014\adapter-checks\lower31-v28-summary.json')
PRIOR=Path(r'E:\dianji\motor-td3-local-results\bidirectional-longhold-20261014\batch1\round1\trial\summary.json')

class Checks(unittest.TestCase):
    def test_negative_transition_uses_actual_ACK_and_old_physical_delta_scale(self):
        from speedloop_stream_training import CausalStream
        from test_speedloop_stream_training import packet,proof
        stream=CausalStream(runtime.LEVELS);source_gain=runtime.LEVELS[2];target=runtime.LEVELS[1]
        for n in range(1,4):
            p=packet(n,kp=source_gain);stream.telemetry(p,proof(p))
        source=packet(3,kp=source_gain)
        command=dict(type='gains',command_seq=1,kp=target,ki=runtime.KI,source_t_us=source['t_us'],expires_us=source['t_us']+100000)
        stream.command(command,source)
        for n in range(4,8):
            p=packet(n,kp=target,applied_seq=1,t_apply_us=source['t_us']+1000)
            result=stream.telemetry(p,proof(p))
        self.assertEqual(result['action_applied'],[target,runtime.KI]);self.assertEqual(result['state']['kp'],source_gain)
        self.assertAlmostEqual(result['physical_delta_action'][0],(target-source_gain)/.00027112)
        self.assertTrue(result['action_mapping_redefinition_required']);self.assertFalse(result['actor_applied'])
    def test_new_gain_stream_is_explicit_and_capture_only(self):
        from speedloop_stream_training import CausalStream,StreamObserver,LOWER31_V28_GAINS
        self.assertEqual(runtime.LEVELS,LOWER31_V28_GAINS)
        self.assertEqual(CausalStream(runtime.LEVELS).allowed_gains,runtime.LEVELS)
        with self.assertRaises(ValueError):CausalStream(runtime.LEVELS+(.0037,))
        with self.assertRaises(ValueError):StreamObserver(ROOT/'rejected-stream',None,runtime.LEVELS,capture_only=False)
        observer=StreamObserver(ROOT/'stream-fixture',None,runtime.LEVELS,capture_only=True)
        result=observer.close();self.assertTrue(result['closed']);self.assertIsNone(result['error'])
    def args(self,phase='prepare',label='fixture'):
        path=ROOT/(label+'.json');path.write_text(json.dumps(runtime.expected_schedule(0)))
        return SimpleNamespace(phase=phase,authorized_lower31_capture=True,gain_mode='kp_probe',
            build=str(BUILD),adapter_checks=str(CHECKS),output=str(ROOT/(label+'-out')),
            schedule_index=0,schedule_contract=str(path),previous_trial_summary=str(PRIOR))
    def test_exact_build_and_phase_scope(self):
        a=self.args();self.assertEqual(runtime.validate(a)['build_id'],runtime.IDENTITY)
        for key,value in [('authorized_lower31_capture',False),('phase','resume'),('gain_mode','baseline'),('apply_shadow_kp',True),('ki_probe_sign',1)]:
            b=deepcopy(a);setattr(b,key,value)
            with self.assertRaises(ValueError):runtime.validate(b)
    def test_stale_or_modified_schedule_rejected(self):
        a=self.args(label='schedule')
        for key,value in [('reserved_motion_seconds',25),('maximum_batch_motion_seconds',49),('fixed_ki',.001476),
                          ('reference_levels_rpm',[800,1000,1200]),('reference_slot_ms',1000),
                          ('gain_reference_clock_offset_ms',0),('whole_boot_role','validation'),('actor_applied',True),
                          ('host_single_kp_step_limit',.00027112),('fault_automatic_retry',True)]:
            cfg=runtime.expected_schedule(0);cfg[key]=value;Path(a.schedule_contract).write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):runtime.validate(a)
    def test_unknown_prior_or_fault_rejected(self):
        a=self.args(label='prior');base=json.loads(PRIOR.read_text());path=ROOT/'prior-copy.json';a.previous_trial_summary=str(path)
        for key,value in [('passed',False),('final_irq_fault',1),('protocol_stop_acknowledged',False),
                          ('bin_sha256','0'*64),('firmware_id','unknown')]:
            modified=dict(base);modified[key]=value;path.write_text(json.dumps(modified))
            with self.assertRaises(ValueError):runtime.validate(a)
    def test_references_and_separated_gain_slots(self):
        for pattern in runtime.PATTERNS:
            self.assertEqual(len(pattern),32)
            self.assertTrue(set(pattern)<=set(range(9)))
            self.assertTrue(all(abs(a-b)<=1 for a,b in zip(pattern,pattern[1:])))
            p=runtime.ReferenceProbe(pattern)
            for ms in range(0,23751,50):
                kp,ki=p.planned(ms);self.assertEqual(ki,runtime.KI)
                self.assertLessEqual(abs(kp-p.actual),.00013556+1e-9)
                p.observe(dict(kp=kp,ki=ki))
                if 6250<=ms<22250:self.assertEqual(kp,runtime.LEVELS[pattern[(ms-6250)//500]])
                if ms>=22450:self.assertEqual(kp,runtime.LEVELS[runtime.BASE_INDEX])
            self.assertTrue(all(abs(d['command_kp']-d['actual_kp'])<=.00013556+1e-9 for d in p.decisions))
        for ms,correct,wrong in [(7997,1000,950),(8003,950,1000),(11997,1000,1050),(12003,1050,1000)]:
            self.assertTrue(runtime.reference_matches(ms,correct));self.assertFalse(runtime.reference_matches(ms,wrong))
        self.assertFalse(runtime.reference_matches(10000,float('nan')))
    def test_missing_ACK_and_clock_gap_fail(self):
        p=runtime.ReferenceProbe(runtime.PATTERNS[0]);p.planned(6250)
        with self.assertRaises(RuntimeError):p.planned(7250)
        with self.assertRaises(RuntimeError):runtime.ReferenceProbe(runtime.PATTERNS[0]).planned(6800)
        p=runtime.ReferenceProbe(runtime.PATTERNS[0]);p.planned(6250)
        with self.assertRaises(RuntimeError):p.observe(dict(kp=.0036,ki=runtime.KI))
        with self.assertRaises(ValueError):p.planned(6300,1)
    def test_trial_needs_exact_new_reader_qualification(self):
        a=self.args(phase='trial',label='reader');a.bounded_reader_benchmark=str(ROOT/'reader.json')
        for value in [dict(passed=False),dict(passed=True,profile='pipelined-chunk8-v2',samples=1000,over_6ms=0,
            firmware_sha256=runtime.PRIOR_SHA,hardware_written=False,reset=False,resume=False,motion_started=False)]:
            Path(a.bounded_reader_benchmark).write_text(json.dumps(value))
            with self.assertRaises(ValueError):runtime.validate(a)
    def test_qualification_is_separate_from_dynamic_capture(self):
        a=self.args(phase='qualify',label='qualification');cfg=runtime.qualification_schedule()
        Path(a.schedule_contract).write_text(json.dumps(cfg));a.authorized_three_second_qualification=True
        self.assertEqual(runtime.validate(a)['build_id'],runtime.IDENTITY)
        a.authorized_three_second_qualification=False
        with self.assertRaises(ValueError):runtime.validate(a)
        a.authorized_three_second_qualification=True;a.phase='trial'
        with self.assertRaises(ValueError):runtime.validate(a)
        a.phase='qualify';cfg['host_stop_seconds']=3.8;Path(a.schedule_contract).write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):runtime.validate(a)
    def test_qualification_stop_and_gain_schedule_actual_dispatch(self):
        a=self.args(phase='qualify',label='qualification-dispatch');a.authorized_three_second_qualification=True
        Path(a.schedule_contract).write_text(json.dumps(runtime.qualification_schedule()))
        can=ModuleType('can');interfaces=ModuleType('can.interfaces');pcan=ModuleType('can.interfaces.pcan')
        basic=ModuleType('can.interfaces.pcan.basic');basic.PCANBasic=lambda:None
        can.interfaces=interfaces;interfaces.pcan=pcan;pcan.basic=basic
        import speedloop_motion_gain_trial as trial
        saved=trial.STOP_SECONDS
        def inspect(args):
            self.assertEqual(trial.STOP_SECONDS,2.8);self.assertEqual(trial.MAX_MOTION_SECONDS,3)
            self.assertEqual(trial.GAIN_CUTOFF_SECONDS,2.7);self.assertEqual(trial.FINAL_GAIN_DEADLINE_SECONDS,2.75)
            for elapsed in (0,2200,2750,2999):self.assertEqual(trial.planned_gains(elapsed),(runtime.LEVELS[runtime.BASE_INDEX],runtime.KI))
            Path(args.output).mkdir();return dict(passed=True,software_fixture_only=True,hardware_accessed=False)
        with patch.dict(sys.modules,{'can':can,'can.interfaces':interfaces,'can.interfaces.pcan':pcan,'can.interfaces.pcan.basic':basic}),patch.object(trial,'trial',inspect):
            result=runtime.run(a)
        self.assertTrue(result['qualification_only']);self.assertFalse(result['new_training_data_admission'])
        self.assertEqual(trial.STOP_SECONDS,saved)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    ROOT=Path(a.output);assert Path('E:/simulink/_codex_tmp').resolve() in ROOT.resolve().parents;ROOT.mkdir(exist_ok=False)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (ROOT/'summary.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,
        hardware_accessed=False,software_fixtures_only=True,motion_started=False,deployment_allowed=False))+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
