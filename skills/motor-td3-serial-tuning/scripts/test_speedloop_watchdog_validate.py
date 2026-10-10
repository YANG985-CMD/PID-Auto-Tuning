"""Power/identity and register evidence rejection checks; no hardware access."""
from types import SimpleNamespace
import struct
import unittest
from unittest.mock import patch
import speedloop_watchdog_validate as v
import speedloop_watchdog_can as live

class Evidence(unittest.TestCase):
    def setUp(self):
        self.trace=('Core 0 (None):  Halted\npc = 0x080001d8\nxpsr = 0x01000000\n'
                    '40021094:  24000000\n40012c00:  00000120\n40012c20:  00000000\n40012c44:  02023078\n')
        self.record=dict.fromkeys(v.FIELDS,0)
        self.record.update(magic=0x53445731,active=1,feeds=60,adc_count=60,tick_count=600)
    def test_power_gate_precedes_file_and_probe_access(self):
        with patch.object(v.Path,'read_text',side_effect=AssertionError('Read before confirmation')):
            with self.assertRaises(ValueError):
                v.run(SimpleNamespace(power_stage_disconnected=False,reset_and_halt_ack=True))
        with self.assertRaises(ValueError): live.prepare(SimpleNamespace(power_stage_disconnected=False))
        with self.assertRaises(ValueError): live.run(SimpleNamespace(allow_live=True,board_power_confirmed=False))
    def test_unrecognized_flash_image_refused(self):
        with self.assertRaises(ValueError): v.validate({},b'wrong')
    def test_status_layout_identity_and_incomplete_data(self):
        raw=struct.pack('<14I',*(self.record[k] for k in v.FIELDS))
        self.assertEqual(v.box(raw)['feeds'],60)
        with self.assertRaises(ValueError): v.box(raw[:-1])
        with self.assertRaises(ValueError): v.box(bytes(56))
    def test_healthy_feeding_requires_all_progress(self):
        v.healthy(self.record,self.trace)
        for k,val in (('fault',6),('feeds',0),('adc_count',0),('tick_count',0),('boot_latched',1)):
            bad=dict(self.record);bad[k]=val
            with self.subTest(key=k),self.assertRaises(ValueError): v.healthy(bad,self.trace)
    def test_every_output_sample_checked(self):
        for line in ('40012c00:  00000121\n','40012c20:  00000001\n','40012c44:  0202b078\n'):
            with self.assertRaises(ValueError): v.off(self.trace+line)
    def test_reset_requires_iwdg_cause_halted_reset_vector_and_thread_mode(self):
        v.reset_caught(self.trace,0x080001D9)
        for trace in (self.trace.replace('24000000','04000000'),self.trace.replace('Halted','Running'),
                      self.trace.replace('080001d8','080001da'),self.trace.replace('01000000','01000003')):
            with self.assertRaises(ValueError): v.reset_caught(trace,0x080001D9)
    def test_can_datagrams_are_only_hello_and_stop(self):
        link=SimpleNamespace(send=lambda frame: None)
        with patch.object(live.time,'sleep'),patch.object(live.wire,'fragment',wraps=live.wire.fragment) as fragment:
            self.assertGreater(live.datagram(link,{'type':'hello','profile_id':v.IDENTITY},7),0)
            self.assertGreater(live.datagram(link,{'type':'stop'},7,99,1),0)
            self.assertEqual(fragment.call_count,2)
            for op in ('begin','gains'):
                with self.assertRaises(ValueError): live.datagram(link,{'type':op},7,99,2)
    def test_collector_requires_watchdog_identity_and_empty_capabilities(self):
        c=live.capture.Collector(7,99,lambda row: None,identity=v.IDENTITY)
        with patch.object(c.rx,'feed',return_value=b'packet'):
            with patch.object(live.wire,'unpack',return_value=(dict(type='hello',firmware_id=v.IDENTITY,profile_id=v.IDENTITY,capabilities=[]),dict(nonce=7,boot=99))):
                c.feed(0x621,bytes(8),0,0)
                self.assertIsNotNone(c.hello)
        c=live.capture.Collector(7,99,lambda row: None,identity=v.IDENTITY)
        with patch.object(c.rx,'feed',return_value=b'packet'),patch.object(live.wire,'unpack',return_value=(dict(type='hello',firmware_id=v.IDENTITY,profile_id=v.IDENTITY,capabilities=['start']),dict(nonce=7,boot=99))):
            with self.assertRaises(live.wire.WireError): c.feed(0x621,bytes(8),0,0)

if __name__=='__main__': unittest.main(verbosity=2)
