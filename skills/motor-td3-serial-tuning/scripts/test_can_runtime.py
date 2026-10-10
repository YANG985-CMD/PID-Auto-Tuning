"""Python <-> compiled C CAN/guard tests. All devices and outputs are software-only."""
import argparse
import copy
import ctypes as ct
import json
import math
import queue
import struct
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import can_transport as wire
import motor_runtime as runtime
from session_checks import audit_rows, load_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = LIB = None
NONCE, BOOT = 0x1234567890ABCDEF, 0x1122334455667788


def profile():
    p = copy.deepcopy(load_json(ROOT/'assets/mock-profile.json'))
    p.update(profile_id='test-can-profile-v1', simulation_only=False)
    p['device'].update(transport='can', bitrate=500000, port='PCAN_USBBUS1',
                       firmware_id='software-can-peer-v1', protocol_id=wire.PROTOCOL)
    p['safety']['max_frame_gap_ms'] = 100
    p['runtime']['max_steps'] = 3
    p['can'] = dict(telemetry_period_ms=20, fragment_timeout_ms=50)
    return p  # Only injected test peers use this profile; never saved as a live template.


def raw_output(name):
    out = ct.create_string_buffer(wire.MAX_PACKET)
    length = getattr(LIB, name)(out)
    return out.raw[:length]


def deliver(obj, seq=0, now=1000, boot=BOOT, nonce=NONCE, expires=300000, tag=0):
    if obj['type'] == 'hello': boot, expires = 0, 0
    packet = wire.pack(obj, nonce, boot, seq, expires)
    result = 0
    for f in wire.fragment(packet, tag): result = LIB.test_feed(f, len(f), now)
    LIB.test_tick(now)
    return packet, result


def handshake():
    assert LIB.test_init(BOOT)
    packet, result = deliver(dict(type='hello', profile_id='test-can-profile-v1'), expires=0)
    assert result == 1
    return wire.unpack(raw_output('test_hello'))


def begin():
    handshake()
    deliver(dict(type='begin',profile_id='test-can-profile-v1',speed_ref=500,lease_ms=5000),seq=1,now=2000)
    assert LIB.test_enabled()


class WireCan:
    """Actual C endpoint behind an in-memory classic-CAN byte queue; no adapter."""
    def __init__(self):
        assert LIB.test_init(BOOT)
        self.lock, self.q = threading.RLock(), queue.Queue()
        self.now = self.tag = 0
        self.closed = self.drop = False
        self.thread = threading.Thread(target=self.loop,daemon=True)
        self.thread.start()

    def emit(self, packet):
        if not packet or self.drop: return
        out = ct.create_string_buffer(8)
        for index in range((len(packet)+3)//4):
            assert LIB.test_fragment(packet,len(packet),self.tag,index,out)
            self.q.put(out.raw)
        self.tag = (self.tag + 1) & 255

    def send(self, frame):
        with self.lock:
            result = LIB.test_feed(frame,len(frame),self.now)
            if result == 1:
                self.now += 1
                LIB.test_tick(self.now)
                self.emit(raw_output('test_hello'))
            if result < 0: LIB.test_tick(self.now)

    def loop(self):
        while not self.closed:
            with self.lock:
                self.now += 20000
                LIB.test_tick(self.now)
                self.emit(raw_output('test_telemetry'))
            time.sleep(.02)

    def receive(self):
        try: return self.q.get(timeout=.001)
        except queue.Empty: return None

    def close(self):
        self.closed = True
        self.thread.join(.1)


class CanTests(unittest.TestCase):
    def setUp(self):
        self.peers = []
        assert LIB.test_init(BOOT)

    def tearDown(self):
        for peer in self.peers: peer.close()

    def test_c_python_codec_and_fragments(self):
        hello, meta = handshake()
        self.assertEqual(hello['protocol_id'], wire.PROTOCOL)
        self.assertEqual(meta['nonce'], NONCE)
        self.assertEqual(len(hello['capabilities']), 6)
        commands = [(dict(type='begin',profile_id='test-can-profile-v1',speed_ref=500,lease_ms=5000),1),
                    (dict(type='gains',command_seq=1,kp=.0034,ki=.00144,lease_ms=5000),2),
                    (dict(type='stop'),3)]
        for obj,seq in commands:
            packet,result=deliver(obj,seq=seq,now=1000+seq*1000)
            self.assertEqual(result,1); self.assertEqual(LIB.test_decode(packet,len(packet)),1)
            out=ct.create_string_buffer(8)
            for index,f in enumerate(wire.fragment(packet,7)):
                self.assertTrue(LIB.test_fragment(packet,len(packet),7,index,out))
                self.assertEqual(out.raw,f)
        packet=raw_output('test_telemetry'); data,meta=wire.unpack(packet)
        self.assertEqual(data['applied_seq'],1); self.assertFalse(data['enabled'])
        self.assertEqual(wire.pack(data,meta['nonce'],meta['boot'],meta['wire_seq']),packet)

    def test_crc_nonfinite_and_unknown_fields(self):
        packet=wire.pack(dict(type='gains',command_seq=1,kp=.0034,ki=.00144,lease_ms=5000),NONCE,BOOT,1,300000)
        for index in range(len(packet)):
            bad=bytearray(packet); bad[index]^=1
            with self.assertRaises(wire.WireError): wire.unpack(bad)
            self.assertFalse(LIB.test_decode(bytes(bad),len(bad)))
        for value in (math.nan,math.inf):
            with self.assertRaises(wire.WireError):
                wire.pack(dict(type='gains',command_seq=1,kp=value,ki=.00144,lease_ms=5000),NONCE,BOOT,1,300000)
        with self.assertRaises(wire.WireError): wire.pack(dict(type='stop',pwm=1),NONCE,BOOT,1)

    def test_fragment_gap_overlap_timeout_and_padding(self):
        packet=wire.pack(dict(type='hello',profile_id='x'),NONCE)
        frames=wire.fragment(packet,4)
        r=wire.Reassembler(); r.feed(frames[0],1)
        with self.assertRaises(wire.WireError): r.feed(frames[2],1.001)
        r=wire.Reassembler(); r.feed(frames[0],1)
        with self.assertRaises(wire.WireError): r.feed(frames[0],1.001)
        r=wire.Reassembler(); r.feed(frames[0],1)
        with self.assertRaises(wire.WireError): r.check_timeout(1.051)
        LIB.test_feed(frames[0],8,1000); LIB.test_tick(51000)
        self.assertEqual(LIB.test_fault(),10)
        r=wire.Reassembler()
        for f in frames[:-1]: r.feed(f,1)
        bad=bytearray(frames[-1]); bad[-1]=1
        with self.assertRaises(wire.WireError): r.feed(bad,1)

    def test_expiry_future_boot_and_session_reject_before_enable(self):
        for changes in (dict(expires=2000),dict(expires=999999),dict(boot=BOOT+1),dict(nonce=NONCE+1),dict(seq=2)):
            with self.subTest(changes=changes):
                handshake(); args=dict(seq=1,now=2000,expires=300000); args.update(changes)
                deliver(dict(type='begin',profile_id='test-can-profile-v1',speed_ref=500,lease_ms=5000),**args)
                self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),10)

    def test_replayed_begin_does_not_restart(self):
        begin()
        deliver(dict(type='stop'),seq=2,now=3000)
        deliver(dict(type='begin',profile_id='test-can-profile-v1',speed_ref=500,lease_ms=5000),seq=1,now=4000)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),10)

    def test_actual_pi_callback_required_for_ack(self):
        for mode in (1,2):
            begin(); LIB.test_apply_mode(mode)
            deliver(dict(type='gains',command_seq=1,kp=.0034,ki=.00144,lease_ms=5000),seq=2,now=3000)
            self.assertEqual(LIB.test_applied(),0)
            self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),11)
            self.assertEqual(LIB.test_kp(),runtime.f32(.003389))

    def test_gain_bounds_atomic_queue_and_sequence(self):
        begin()
        obj=dict(type='gains',command_seq=1,kp=.004,ki=.00144,lease_ms=5000)
        deliver(obj,seq=2,now=3000)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_applied(),0)
        begin()
        packet=wire.pack(dict(type='gains',command_seq=1,kp=.0034,ki=.00144,lease_ms=5000),NONCE,BOOT,2,300000)
        for f in wire.fragment(packet,1): LIB.test_feed(f,8,3000)
        self.assertEqual(LIB.test_applied(),0)  # RX alone cannot write PI.
        LIB.test_tick(3000)
        self.assertEqual(LIB.test_applied(),1)
        deliver(dict(type='gains',command_seq=1,kp=.0034,ki=.00144,lease_ms=5000),seq=3,now=4000)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),3)

    def test_independent_lease_link_and_current(self):
        begin(); LIB.test_tick(5002000)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),7)
        begin(); LIB.test_link_timeout(500); LIB.test_tick(2500)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),8)
        begin(); LIB.test_current(4); LIB.test_tick(3000)
        self.assertFalse(LIB.test_enabled()); self.assertEqual(LIB.test_fault(),4)
        # A second hello never refreshes the active lease or clears the fault.
        deadline=LIB.test_deadline()
        deliver(dict(type='hello',profile_id='test-can-profile-v1'),now=4000)
        self.assertEqual(LIB.test_deadline(),deadline); self.assertFalse(LIB.test_enabled())

    def test_reference_allowlist_and_queue_overflow(self):
        handshake()
        deliver(dict(type='begin',profile_id='test-can-profile-v1',speed_ref=999,lease_ms=5000),seq=1,now=2000)
        self.assertFalse(LIB.test_enabled())
        handshake()
        packet=wire.pack(dict(type='stop'),NONCE,BOOT,1)
        for tag in (0,1):
            for f in wire.fragment(packet,tag): LIB.test_feed(f,8,2000)
        LIB.test_tick(2000)
        self.assertEqual(LIB.test_fault(),10)

    def test_runtime_gate_before_driver_access(self):
        p=profile()
        runtime.validate_runtime(p,True,'can')
        for change in ('simulation_only','protocol','rate','period','limits'):
            bad=copy.deepcopy(p)
            if change=='simulation_only': bad['simulation_only']=True
            elif change=='protocol': bad['device']['protocol_id']=runtime.PROTOCOL
            elif change=='rate': bad['device']['bitrate']=1000000
            elif change=='period': bad['can']['telemetry_period_ms']=5
            else: bad['safety']['firmware_link_loss_verified']=False
            with patch.object(wire,'PcanLink') as factory:
                with self.assertRaises(runtime.SafetyError): runtime.CanDevice(bad)
                factory.assert_not_called()

    def test_pcan_ownership_mode_and_driver_error(self):
        class Message:
            def __init__(self): self.ID,self.MSGTYPE,self.LEN,self.DATA=0,0,0,[0]*8
        basic=SimpleNamespace(PCAN_CHANNEL_NAMES={'PCAN_USBBUS1':81},PCAN_CHANNEL_CONDITION=1,
            PCAN_CHANNEL_AVAILABLE=1,PCAN_LISTEN_ONLY=2,PCAN_PARAMETER_OFF=0,PCAN_BITRATES={500000:28},
            PCAN_ERROR_OK=0,PCAN_ERROR_QRCVEMPTY=32,PCAN_MESSAGE_STANDARD=0,TPCANMsg=Message)
        class Api:
            def __init__(self): self.calls=[]; self.mode=0; self.available=1; self.preset=0; self.post=0; self.write_error=0
            def GetValue(self,h,k): return 0,self.available if k==1 else self.mode
            def SetValue(self,h,k,v): self.calls.append('preset'); self.mode=v; return self.preset
            def Initialize(self,h,b): self.calls.append('init'); self.mode=self.post; return 0
            def Uninitialize(self,h): self.calls.append('close'); return 0
            def Write(self,h,msg): self.calls.append('write'); self.msg=msg; return self.write_error
            def Read(self,h): return 32,Message(),None
        api=Api(); api.available=0
        with self.assertRaises(wire.WireError): wire.PcanLink('PCAN_USBBUS1',api,basic)
        self.assertFalse(api.calls)
        api=Api(); api.preset=1
        with self.assertRaises(wire.WireError): wire.PcanLink('PCAN_USBBUS1',api,basic)
        self.assertNotIn('init',api.calls)
        api=Api(); api.post=1
        with self.assertRaises(wire.WireError): wire.PcanLink('PCAN_USBBUS1',api,basic)
        self.assertIn('close',api.calls)
        api=Api(); link=wire.PcanLink('PCAN_USBBUS1',api,basic)
        data=wire.fragment(wire.pack(dict(type='hello',profile_id='x'),NONCE),0)[0]
        api.mode=1
        with self.assertRaises(wire.WireError): link.send(data)
        self.assertNotIn('write',api.calls)
        api.mode=0; api.write_error=16
        with self.assertRaises(wire.WireError): link.send(data)
        self.assertEqual(api.msg.ID,0x620)
        self.assertEqual(api.msg.DATA[0],0xD1); link.close()

    def test_nonzero_disabled_feedback_is_not_fabricated(self):
        begin()
        # The endpoint reports actual gains, and applies no new ACK on a rejected update.
        before=LIB.test_kp()
        deliver(dict(type='gains',command_seq=1,kp=.1,ki=.1,lease_ms=5000),seq=2,now=3000)
        telemetry,meta=wire.unpack(raw_output('test_telemetry'))
        self.assertEqual(telemetry['kp'],before)
        self.assertEqual(telemetry['applied_seq'],0)
        self.assertFalse(telemetry['enabled']); self.assertNotEqual(telemetry['fault'],0)

    def test_engine_experiences_over_compiled_c_can(self):
        peer=WireCan(); self.peers.append(peer)
        p=profile(); device=runtime.CanDevice(p,link=peer)
        engine=runtime.Engine(p,OUTPUT/'can-engine',device=device,live=True,transport='can')
        try:
            engine.reset(1,0,'baseline')
            rows=[engine.step([.1,-.1])['transition'] for _ in range(3)]
            checked=audit_rows(rows,p)
            self.assertTrue(checked['trainable'],checked); self.assertEqual(checked['eligible'],3)
            self.assertTrue(rows[-1]['truncated']); self.assertFalse(LIB.test_enabled())
            self.assertEqual(rows[1]['state'],rows[0]['next_state'])
            self.assertEqual(rows[-1]['protocol_id'],wire.PROTOCOL)
        finally: engine.close()

    def test_telemetry_loss_not_confirmed_as_applied(self):
        peer=WireCan(); self.peers.append(peer)
        device=runtime.CanDevice(profile(),link=peer)
        try:
            device.reset(1,500)
            peer.drop=True
            with self.assertRaises(runtime.SafetyError): device.apply(1,dict(kp=runtime.f32(.0034),ki=runtime.f32(.00144)))
            self.assertFalse(device.stop())
            with peer.lock: LIB.test_tick(peer.now+5000000)
            self.assertFalse(LIB.test_enabled())
        finally: device.close()

    def test_fault_blocks_learning_but_keeps_real_stop_feedback(self):
        peer=WireCan(); self.peers.append(peer)
        device=runtime.CanDevice(profile(),link=peer)
        try:
            device.reset(1,500)
            with peer.lock: LIB.test_apply_mode(1)
            with self.assertRaises(runtime.SafetyError):
                device.apply(1,dict(kp=runtime.f32(.0034),ki=runtime.f32(.00144)))
            self.assertEqual(LIB.test_applied(),0)
            self.assertTrue(device.stop())
            with self.assertRaises(runtime.SafetyError): device.reset(2,500)
            self.assertFalse(LIB.test_enabled())
        finally: device.close()

    def test_wrong_firmware_gets_no_post_handshake_command(self):
        peer=WireCan(); self.peers.append(peer)
        p=profile(); p['device']['firmware_id']='different-firmware'
        with self.assertRaises(runtime.SafetyError): runtime.CanDevice(p,link=peer)
        self.assertEqual(LIB.test_wireseq(),0)
        self.assertFalse(LIB.test_enabled()); self.assertTrue(peer.closed)


def main():
    global OUTPUT, LIB
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',required=True); p.add_argument('--compiler',default='gcc')
    args=p.parse_args(); OUTPUT=Path(args.output).resolve(); OUTPUT.mkdir(parents=True,exist_ok=False)
    library=OUTPUT/('can-peer.dll' if sys.platform=='win32' else 'can-peer.so')
    fw=ROOT/'firmware'
    result=subprocess.run([args.compiler,'-std=c99','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
        str(fw/'motor_td3_guard.c'),str(fw/'motor_td3_can.c'),str(fw/'motor_td3_can_control.c'),
        str(fw/'tests/can_test_peer.c'),'-lm','-o',str(library)],capture_output=True,text=True)
    (OUTPUT/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8'); result.check_returncode()
    LIB=ct.CDLL(str(library))
    LIB.test_init.argtypes=[ct.c_uint64]
    LIB.test_feed.argtypes=[ct.c_char_p,ct.c_uint,ct.c_uint64]
    LIB.test_tick.argtypes=[ct.c_uint64]
    for name in ('test_hello','test_telemetry'): getattr(LIB,name).argtypes=[ct.c_void_p]
    LIB.test_fragment.argtypes=[ct.c_char_p,ct.c_uint,ct.c_uint,ct.c_uint,ct.c_void_p]
    LIB.test_decode.argtypes=[ct.c_char_p,ct.c_uint]
    LIB.test_kp.restype=ct.c_float; LIB.test_deadline.restype=ct.c_uint64
    LIB.test_apply_mode.argtypes=[ct.c_int]; LIB.test_current.argtypes=[ct.c_float]; LIB.test_link_timeout.argtypes=[ct.c_uint32]
    tests=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CanTests))
    report=dict(tests=tests.testsRun,passed=tests.wasSuccessful(),hardware_opened=False,
                physical_motor_control_performed=False,compiled_c_endpoint=True)
    (OUTPUT/'can-runtime-tests.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if tests.wasSuccessful() else 1

if __name__=='__main__': raise SystemExit(main())
