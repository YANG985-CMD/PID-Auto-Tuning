"""Existing Python CAN packets -> real generated PI -> actual protocol telemetry.

Requires the private model library built by --can-pi. Hooks are software-only;
no PCAN adapter, probe or board is opened by this test.
"""
import argparse
import ctypes as ct
import json
import os
import unittest
from pathlib import Path
import can_transport as wire

LIB=None
NONCE,BOOT=0x1234567890abcdef,0x1122334455667788


def ticks(n):
    for _ in range(n):LIB.test_base_tick()


def send(kind,seq=0,expires=None,**values):
    now=LIB.test_time();hello=kind=='hello'
    obj=dict(type=kind,**values)
    if kind in ('hello','begin'):obj['profile_id']='speedloop-can-test'
    packet=wire.pack(obj,NONCE,0 if hello else BOOT,seq,0 if hello else (expires or now+50000))
    result=0
    for frame in wire.fragment(packet,seq&255):result=LIB.test_feed(frame)
    return result


def response(name):
    buf=ct.create_string_buffer(wire.MAX_PACKET);length=getattr(LIB,name)(buf)
    return wire.unpack(buf.raw[:length])[0] if length else None


def ready():
    assert LIB.test_init(0)
    assert send('hello')==1
    ticks(1);assert response('test_hello')['type']=='hello'
    assert send('begin',seq=1,speed_ref=500,lease_ms=50)==1
    ticks(10);assert LIB.test_enabled()


def gains(seq=2,command_seq=1,**kw):
    return send('gains',seq=seq,command_seq=command_seq,kp=.0038,ki=.0017,lease_ms=50,**kw)


class ConnectedPI(unittest.TestCase):
    def setUp(self):ready()
    def test_received_packet_waits_for_real_pi_boundary(self):
        old=(LIB.test_kp(),LIB.test_ki());self.assertEqual(gains(),1)
        ticks(9);self.assertEqual((LIB.test_kp(),LIB.test_ki()),old);self.assertEqual(LIB.test_applied(),0)
        ticks(1);self.assertEqual(LIB.test_applied(),1)
        self.assertAlmostEqual(LIB.test_kp(),.0038,places=8);self.assertAlmostEqual(LIB.test_ki(),.0017,places=8)
    def test_actual_ack_is_not_receive_time_or_queued_sequence(self):
        arrived=LIB.test_time();gains()
        pending=response('test_telemetry');self.assertEqual(pending['applied_seq'],0)
        ticks(10);t=response('test_telemetry')
        self.assertEqual(t['applied_seq'],1);self.assertEqual(t['t_apply_us'],2100)
        self.assertEqual(t['t_apply_us'],LIB.test_apply_time());self.assertGreater(t['t_apply_us'],arrived)
        self.assertEqual(LIB.test_pi_sequence(),2)
        self.assertAlmostEqual(t['kp'],LIB.test_kp());self.assertAlmostEqual(t['ki'],LIB.test_ki())
    def test_can_gain_commit_keeps_integral_output_continuous(self):
        gains();ticks(10);self.assertAlmostEqual(LIB.test_before(),LIB.test_after(),places=6)
    def test_generated_reset_defers_valid_gain_packet(self):
        gains();LIB.test_reset(1);ticks(10);self.assertEqual(LIB.test_applied(),0)
        LIB.test_reset(0);ticks(10);self.assertEqual(LIB.test_applied(),1)
    def test_reset_does_not_extend_packet_expiry(self):
        gains(expires=2000);LIB.test_reset(1);ticks(10)
        self.assertEqual(LIB.test_applied(),0);self.assertTrue(LIB.test_fault());self.assertFalse(LIB.test_enabled())
    def test_stop_remains_responsive_during_reset(self):
        LIB.test_reset(1);send('stop',seq=2);ticks(10);self.assertFalse(LIB.test_enabled())
    def test_replayed_action_stops_without_a_second_application(self):
        gains();ticks(10);gains(seq=3);ticks(10)
        self.assertTrue(LIB.test_fault());self.assertFalse(LIB.test_enabled());self.assertEqual(LIB.test_applied(),1)
    def test_sensor_fault_prevents_queued_gain_application(self):
        gains();LIB.test_sensor(9,25);ticks(10)
        self.assertTrue(LIB.test_fault());self.assertFalse(LIB.test_enabled());self.assertEqual(LIB.test_applied(),0)
    def test_missing_temperature_is_not_fabricated_in_telemetry(self):
        LIB.test_sensor(0,float('nan'));self.assertIsNone(response('test_telemetry'))
        ticks(10);self.assertFalse(LIB.test_enabled());self.assertTrue(LIB.test_fault())
    def test_locked_board_identity_still_rejects_motion(self):
        self.assertTrue(LIB.test_init(1));send('hello');ticks(1)
        hello=response('test_hello');self.assertEqual(hello['capabilities'],[])
        send('begin',seq=1,speed_ref=500,lease_ms=50);ticks(10)
        self.assertFalse(LIB.test_enabled());self.assertEqual(LIB.test_pi_sequence(),0)


def run_checks(library,out):
    global LIB
    out=Path(out).resolve()
    if os.name=='nt' and Path('E:/simulink/_codex_tmp').resolve() not in out.parents:
        raise ValueError('Windows temporary output must be under E:/simulink/_codex_tmp')
    out.mkdir(parents=True,exist_ok=True);LIB=ct.CDLL(str(Path(library).resolve()))
    LIB.test_time.restype=LIB.test_apply_time.restype=ct.c_uint64
    LIB.test_sensor.argtypes=[ct.c_float,ct.c_float]
    for name in ('kp','ki','before','after'):getattr(LIB,'test_'+name).restype=ct.c_float
    with (out/'checks.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConnectedPI))
    summary=dict(schema_version=1,tests=result.testsRun,passed=result.wasSuccessful(),
        scope='existing Python CAN protocol with actual generated SpeedLoop PI and software board hooks',
        hardware_accessed=False,physical_can_retested=False,motion_approved=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if not summary['passed']:raise RuntimeError('CAN-to-PI checks failed; inspect checks.log')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--library',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(run_checks(a.library,a.output)))
