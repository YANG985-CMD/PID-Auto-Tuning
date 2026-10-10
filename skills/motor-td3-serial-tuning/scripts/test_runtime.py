#!/usr/bin/env python3
"""Fault and causality tests. Only mock devices; all artifacts need --output."""
import argparse
import copy
import json
import math
import socket
import subprocess
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_runtime import (Engine, MockDevice, SafetyError, SerialDevice, decode_frame,
                           encode_frame, map_action, serve, validate_runtime)
from session_checks import audit_rows, load_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = None


class WireSerial:
    """Byte-stream virtual serial peer for the actual CRC/reader/ACK adapter."""
    def __init__(self, **kwargs):
        self.device = MockDevice(load_json(ROOT / 'assets/mock-profile.json'))
        self.closed = True
        self.pending = bytearray()
        self.lock = threading.Lock()
        self.handshaken = False
        self.port = None

    def open(self):
        self.closed = False
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def emit(self, obj):
        with self.lock:
            self.pending.extend(encode_frame(obj))

    def loop(self):
        while not self.closed:
            if self.handshaken:
                if self.device.enabled:
                    f = self.device.window(self.device.frame(),5)[-1]
                else:
                    with self.device.lock:
                        self.device.seq += 1
                        self.device.t += 5000
                    f = self.device.frame()
                f.update(type='telemetry',boot_id='wire-boot')
                self.emit(f)
            time.sleep(.005)

    def write(self, line):
        req = decode_frame(line)
        op = req['type']
        if op == 'hello':
            self.emit(dict(type='hello',protocol_id='motor-td3-json-crc-v1',firmware_id='mock-plant-v1',
                           profile_id=req['profile_id'],boot_id='wire-boot',
                           capabilities=['atomic_gains','applied_feedback','lease','link_watchdog','fault_latch','single_owner']))
            self.handshaken = True
        elif op == 'begin':
            self.device.reset(1,req['speed_ref'])
        elif op == 'gains':
            self.device.apply(req['command_seq'],req)
        elif op == 'stop':
            self.device.stop()
        return len(line)

    def read(self, size):
        with self.lock:
            if self.pending:
                out = bytes(self.pending[:size])
                del self.pending[:size]
                return out
        time.sleep(.001)
        return b''

    def close(self):
        self.closed = True
        self.thread.join(.1)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.p = load_json(ROOT / 'assets/mock-profile.json')
        self.engines = []

    def engine(self, device=None):
        directory = OUTPUT / self.id().split('.')[-1] / str(len(self.engines))
        directory.mkdir(parents=True,exist_ok=True)
        engine = Engine(copy.deepcopy(self.p), directory,device=device)
        self.engines.append(engine)
        return engine

    def tearDown(self):
        for engine in self.engines:
            engine.close()

    def test_complete_episode_audits_actual_actions(self):
        engine = self.engine()
        engine.reset(1,0,'test-policy')
        rows = []
        for _ in range(self.p['runtime']['max_steps']):
            rows.append(engine.step([.1,-.1])['transition'])
        result = audit_rows(rows,self.p)
        self.assertTrue(result['trainable'],result)
        self.assertEqual(result['eligible'],30)
        self.assertTrue(rows[-1]['truncated'])
        self.assertFalse(engine.device.enabled)
        self.assertEqual(rows[1]['state'],rows[0]['next_state'])

    def test_crc_duplicate_nan_overflow(self):
        good = encode_frame({'speed':12.5})
        self.assertEqual(decode_frame(good)['speed'],12.5)
        for bad in (good.replace(b'12.5',b'13.5'),b'x\n',b'x' * 17000+b'\n'):
            with self.assertRaises(SafetyError): decode_frame(bad)
        import zlib
        for payload in (b'{"x":NaN}',b'{"x":1e999}',b'{"x":1,"x":2}'):
            bad = payload+b'*'+('%08x'%zlib.crc32(payload)).encode()+b'\n'
            with self.assertRaises(SafetyError): decode_frame(bad)

    def test_action_bounds_float32_and_hold(self):
        engine = self.engine(); reset = engine.reset(1,0,'test')
        state = reset['state']
        self.assertEqual(map_action([0,0],state,self.p),{g:state[g] for g in ('kp','ki')})
        for action in ([math.nan,0],[math.inf,0],[1.001,0],[True,0],[0],[0,'x']):
            with self.assertRaises(SafetyError): map_action(action,state,self.p)
        for _ in range(100):
            state.update(map_action([1,-1],state,self.p))
        self.assertLessEqual(state['kp'],self.p['controller']['kp_max'])
        self.assertGreaterEqual(state['ki'],self.p['controller']['ki_min'])

    def test_extreme_action_float32_step_still_audits(self):
        for action in ([1,1],[-1,-1]):
            engine=self.engine(); engine.reset(1,0,'extreme-test')
            rows=[engine.step(action)['transition'] for _ in range(30)]
            result=audit_rows(rows,self.p)
            self.assertTrue(result['trainable'],result)

    def test_mock_profile_cannot_run_live(self):
        with self.assertRaises(SafetyError): validate_runtime(self.p,True)
        bad = copy.deepcopy(self.p); bad['safety']['independent_overcurrent_verified']=False
        with self.assertRaises(SafetyError): validate_runtime(bad)
        bad = load_json(ROOT/'assets/session-profile.example.json')
        with self.assertRaises(SafetyError): validate_runtime(bad,True)

    def test_current_saturation_threshold_is_bounded(self):
        for value in (0, self.p['safety']['current_limit_a'] + .01, math.nan):
            bad = copy.deepcopy(self.p)
            bad['runtime']['current_saturation_a'] = value
            with self.assertRaises(SafetyError): validate_runtime(bad)

    def test_alternative_thermal_profile_cannot_bypass_live_guard(self):
        bad = copy.deepcopy(self.p)
        bad['safety']['thermal_protection'] = 'verified_alternative'
        with self.assertRaisesRegex(SafetyError, 'Alternative thermal protection'):
            validate_runtime(bad)
        bad['simulation_only'] = False
        bad['mode'] = 'evaluate'
        bad['device']['port'] = 'UNOPENED_TEST_PORT'
        with self.assertRaisesRegex(SafetyError, 'Alternative thermal protection'):
            validate_runtime(bad, live=True)

    def test_overcurrent_nan_unknown_endpoint_not_learned(self):
        for value in (5.0,math.nan):
            device = MockDevice(self.p)
            original = device.window
            def bad_window(ack,duration):
                frames=original(ack,duration)
                frames[2]['current']=value
                return frames
            device.window=bad_window
            engine = self.engine(device); engine.reset(1,0,'test')
            with self.assertRaises(SafetyError): engine.step([0,0])
            self.assertFalse(device.enabled)
            self.assertIsNotNone(engine.latched)
            self.assertEqual((engine.output/'transitions.jsonl').read_text(), '')
            with self.assertRaises(SafetyError): engine.reset(2,0,'test')

    def test_ack_gain_and_sequence_mismatch(self):
        for key in ('applied_seq','kp','t_apply_us'):
            device=MockDevice(self.p); original=device.apply
            def bad_apply(seq,gains):
                ack=original(seq,gains)
                ack[key]=seq+1 if key=='applied_seq' else (99 if key=='kp' else ack['t_us']+999999)
                return ack
            device.apply=bad_apply
            engine=self.engine(device); engine.reset(1,0,'test')
            with self.assertRaises(SafetyError): engine.step([0,0])
            self.assertIsNotNone(engine.latched)

    def test_monitor_stops_stalled_learner_and_latches(self):
        self.p['safety']['action_lease_ms']=500
        self.p['safety']['learner_progress_timeout_ms']=80
        engine=self.engine(); engine.reset(1,0,'test')
        time.sleep(.15)
        self.assertFalse(engine.device.enabled)
        self.assertIsNotNone(engine.latched)
        with self.assertRaises(SafetyError): engine.reset(2,0,'test')

    def test_device_lease_survives_host_monitor_loss(self):
        self.p['safety']['action_lease_ms']=30
        device=MockDevice(self.p); device.reset(1,500)
        time.sleep(.06)
        self.assertFalse(device.frame()['enabled'])
        self.assertTrue(device.frame()['fault'])

    def test_time_budget_and_operator_stop_no_restart(self):
        self.p['safety']['max_session_seconds']=4
        engine=self.engine(); engine.reset(1,0,'test'); engine.step([0,0]); engine.stop()
        with self.assertRaises(SafetyError): engine.reset(2,0,'test')

    def test_actual_serial_byte_stream_adapter(self):
        with patch.dict(sys.modules, {'serial':types.SimpleNamespace(Serial=WireSerial)}):
            adapter=SerialDevice(self.p)
            try:
                start=adapter.reset(1,500)
                gains={'kp':start['kp'],'ki':start['ki']}
                ack=adapter.apply(1,gains)
                frames=adapter.window(ack,100)
                self.assertTrue(frames[-1]['enabled'])
                self.assertEqual(frames[-1]['applied_seq'],1)
                self.assertGreaterEqual(frames[-1]['t_us']-ack['t_apply_us'],100000)
                self.assertTrue(adapter.stop())
                self.assertFalse(adapter.frame()['enabled'])
            finally: adapter.close()

    def test_serial_sequence_clock_boot_stale_and_missing_ack(self):
        with patch.dict(sys.modules, {'serial':types.SimpleNamespace(Serial=WireSerial)}):
            for fault in ('sequence','clock','boot','stale','missing-ack'):
                with self.subTest(fault=fault):
                    adapter=SerialDevice(self.p)
                    try:
                        if fault=='sequence':
                            with adapter.port.device.lock: adapter.port.device.seq+=10
                        elif fault=='clock':
                            with adapter.port.device.lock: adapter.port.device.t=-1000000
                        elif fault=='boot':
                            f=adapter.port.device.frame()
                            f.update(type='telemetry',boot_id='new-boot')
                            adapter.port.emit(f)
                        elif fault=='stale':
                            adapter.port.handshaken=False
                        else:
                            adapter.reset(1,500)
                            original=adapter.port.write
                            adapter.port.write=lambda line: len(line) if decode_frame(line)['type']=='gains' else original(line)
                            with self.assertRaises(SafetyError):
                                adapter.apply(1,dict(kp=adapter.frame()['kp'],ki=adapter.frame()['ki']))
                            continue
                        time.sleep(.035)
                        with self.assertRaises(SafetyError): adapter.frame()
                    finally: adapter.close()

    def test_rpc_token_and_disconnect(self):
        engine=self.engine()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
        server=threading.Thread(target=serve,args=(engine,port,'test-token'),daemon=True)
        server.start()
        time.sleep(.03)
        with socket.create_connection(('127.0.0.1',port)) as conn:
            conn.sendall(b'{"op":"hello","token":"wrong"}\n')
            self.assertFalse(json.loads(conn.recv(4096))['ok'])
        with socket.create_connection(('127.0.0.1',port)) as conn:
            stream=conn.makefile('rwb',buffering=0)
            def rpc(req):
                stream.write((json.dumps(req)+'\n').encode()); return json.loads(stream.readline())
            self.assertTrue(rpc(dict(op='hello',token='test-token'))['ok'])
            self.assertTrue(rpc(dict(op='reset',seed=1,ref_index=0,policy_version='test'))['ok'])
            stream.close()
        time.sleep(.03)
        self.assertIsNotNone(engine.latched)
        with socket.create_connection(('127.0.0.1',port)) as conn:
            conn.sendall(b'{"op":"hello","token":"test-token"}\n'); conn.recv(4096)
            conn.sendall(b'{"op":"shutdown"}\n'); conn.recv(4096)
        server.join(1)
        self.assertFalse(server.is_alive())


def main():
    global OUTPUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    OUTPUT=Path(args.output); OUTPUT.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                hardware_access=False,passed=result.wasSuccessful())
    (OUTPUT/'runtime-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
