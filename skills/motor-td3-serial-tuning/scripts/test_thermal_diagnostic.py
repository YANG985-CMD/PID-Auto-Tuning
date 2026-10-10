"""Hardware-entry rejection/cleanup tests with substitutes; never opens hardware."""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib
import thermal_diagnostic as d
import can_transport as wire
import thermal_can as heat

OUT=None
NONCE,BOOT=7,0x1234567812345678


def manifest():
    m=json.loads((Path(__file__).resolve().parents[3]/'examples/thermal-can/build-summary.json').read_text())
    m['symbols']=d.SYMBOLS.copy();m['thermal_state_layout']=d.LAYOUT.copy()
    return m


def fake_image():
    data=bytearray(d.IMAGE_BYTES);struct.pack_into('<II',data,0,0x20008000,d.ENTRY)
    return bytes(data)


def heat_packet(seq):
    rows=[json.loads(s) for s in (Path(__file__).resolve().parents[3]/'examples/thermal-can/synthetic-raw.jsonl').read_text().splitlines()]
    data=bytearray(b''.join(bytes.fromhex(r['data_hex'])[4:] for r in rows if r['arbitration_id']==heat.CAN_ID))
    struct.pack_into('<I',data,24,seq);struct.pack_into('<Q',data,36,seq*100000)
    struct.pack_into('<I',data,140,zlib.crc32(data[:140]));return data


def thermal_ram():
    data=bytearray(d.LAYOUT['size'])
    for name,value in (('guard_fault',1),('initialized',1),('fault',2)):
        struct.pack_into('<I',data,d.LAYOUT[name],value)
    return bytes(data)


class Clock:
    def __init__(self): self.now=0.;self.worker=None;self.cleanup=False;self.extra=None;self.seq_at_hold=None
    def __call__(self): return self.now
    def sleep(self,seconds):
        self.now+=seconds
        if self.worker and self.worker.completed:
            if not self.cleanup: self.worker.stop.set()
            elif self.extra is None:
                self.extra=self.now+.16;self.seq_at_hold=self.worker.stop_seq;self.worker.holding.set()
            elif self.now>=self.extra: self.worker.stop.set()


class Link:
    def __init__(self,clock,bad=False,no_heat=False):
        self.clock=clock;self.sent=[];self.handle=1;self.api=self
        self.basic=SimpleNamespace(PCAN_ERROR_QRCVEMPTY=32,PCAN_MESSAGE_STANDARD=0)
        self.rx=deque();self.closed=False
        reply=wire.pack(dict(type='hello_reply',firmware_id=d.IDENTITY,profile_id=d.IDENTITY,capabilities=[]),NONCE,BOOT)
        for f in wire.fragment(reply,1): self.rx.append((.01,0x621,f))
        for i in range(75):
            at=.02+i*.1
            if not no_heat:
                data=heat_packet(i+1)
                for k in range(36): self.rx.append((at,heat.CAN_ID,bytes([0xD1,(i+1)%256,k,144])+data[k*4:k*4+4]))
            status=struct.pack('<BBHBBH',1,12,7 if bad and i==2 else 3,3,0,5)
            for identifier,data in ((0x622,status),(0x623,struct.pack('<ff',.003389,.00144)),
                                   (0x624,struct.pack('<ff',24,.03)),(0x625,b'\0'*8)):
                self.rx.append((at,identifier,data))
    value=staticmethod(int)
    def mode(self): pass
    def send(self,data): self.sent.append(data)
    def check(self,status):
        if status: raise ValueError('Driver failure')
    def Read(self,handle):
        if not self.rx or self.rx[0][0]>self.clock(): return 32,None,None
        at,identifier,data=self.rx.popleft()
        return 0,SimpleNamespace(ID=identifier,MSGTYPE=0,LEN=8,DATA=data),SimpleNamespace(micros=0,millis=int(at*1000),millis_overflow=0)
    def close(self): self.closed=True


class EntryTests(unittest.TestCase):
    def test_power_gates_precede_file_probe_and_can_access(self):
        with patch.object(d,'load_build',side_effect=AssertionError('file access')), \
             patch.object(d,'load_session',side_effect=AssertionError('session access')):
            for function,args in ((d.flash,dict(power_stage_disconnected=False,reset_and_halt_ack=True)),
                                  (d.prepare,dict(power_stage_disconnected=False)),
                                  (d.run,dict(allow_live=True,board_power_confirmed=False)),
                                  (d.finish,dict(power_stage_disconnected=False))):
                with self.assertRaises(ValueError): function(SimpleNamespace(**args))
    def test_unknown_image_or_changed_hex_rejected(self):
        for binary,hex_data in ((b'wrong',b'wrong'),(fake_image(),b'wrong')):
            with self.assertRaises(ValueError): d.validate(manifest(),binary,hex_data)
    def test_missing_can_dependency_precedes_prepare_probe_and_files(self):
        with patch.object(d,'check_can_dependencies',side_effect=ValueError('missing library')), \
             patch.object(d,'load_build',side_effect=AssertionError('file access')), \
             patch.object(d,'debug',side_effect=AssertionError('probe access')):
            with self.assertRaisesRegex(ValueError,'missing library'):
                d.prepare(SimpleNamespace(power_stage_disconnected=True))
    def test_missing_dependency_does_not_consume_run_session(self):
        with patch.object(d,'check_can_dependencies',side_effect=ValueError('missing library')), \
             patch.object(d,'load_session',side_effect=AssertionError('session access')), \
             patch.object(d.wire,'PcanLink',side_effect=AssertionError('CAN access')):
            with self.assertRaisesRegex(ValueError,'missing library'):
                d.run(SimpleNamespace(allow_live=True,board_power_confirmed=True))
    def test_contract_source_offsets_and_symbols_cannot_be_changed(self):
        binary=fake_image();hex_data=b'fake hex'
        actual=d.sha
        def fake_digest(value):
            if value==binary: return d.BIN_SHA
            if value==hex_data: return d.HEX_SHA
            return actual(value)
        with patch.object(d,'sha',side_effect=fake_digest):
            d.validate(manifest(),binary,hex_data)
            for key,value in (('firmware_id','other'),('capabilities',1),('thermal_state_layout',{}),
                              ('current_gain_calibrated',True),('motion_enable_implemented',True),
                              ('integration_sha256',{}),('model_sha256','wrong')):
                m=manifest();m[key]=value
                with self.assertRaises(ValueError): d.validate(m,binary,hex_data)
            m=manifest();m['symbols']['motor_td3_g431_debugger_boot_token']+=4
            with self.assertRaises(ValueError): d.validate(m,binary,hex_data)
    def test_ram_rejection_requires_exact_missing_calibration_state(self):
        self.assertFalse(d.thermal_state(thermal_ram())['motion_approved'])
        for name in ('fault','guard_fault','guard_configured','seed_known','calibrated','initialized','has_window'):
            data=bytearray(thermal_ram());struct.pack_into('<I',data,d.LAYOUT[name],99)
            with self.assertRaises(ValueError): d.thermal_state(data)
        with self.assertRaises(ValueError): d.thermal_state(thermal_ram()[:-1])
    def test_every_pwm_sample_is_checked(self):
        text='40012c00:  00000000\n40012c20:  00000000\n40012c44:  00000000\n'
        d.old.off(text)
        for address,value in ((0x40012c00,1),(0x40012c20,1),(0x40012c44,0x8000)):
            with self.assertRaises(ValueError): d.old.off(text+f'{address:08x}:  {value:08x}\n')
    def test_bounded_worker_sends_only_hello_and_stop(self):
        clock=Clock();link=Link(clock);out=OUT/'worker-good';out.mkdir()
        worker=d.Worker(link,NONCE,BOOT,out,clock,clock.sleep);clock.worker=worker;worker.run()
        self.assertIsNone(worker.error);self.assertTrue(worker.completed)
        self.assertTrue(heat.audit(worker.rows)[0]['passed']);self.assertGreaterEqual(worker.stop_seq,50)
        rx=wire.Reassembler();commands=[]
        for frame in link.sent:
            data=rx.feed(frame,0)
            if data: commands.append(wire.unpack(data)[0]['type'])
        self.assertEqual(commands[0],'hello');self.assertEqual(set(commands),{'hello','stop'})
        self.assertLess(worker.elapsed,3.1)
    def test_heartbeat_continues_during_halt_then_retires(self):
        clock=Clock();clock.cleanup=True;link=Link(clock);out=OUT/'worker-hold';out.mkdir()
        worker=d.Worker(link,NONCE,BOOT,out,clock,clock.sleep);clock.worker=worker;worker.run()
        self.assertIsNone(worker.error);self.assertGreaterEqual(worker.stop_seq,clock.seq_at_hold+2)
        self.assertGreater((out/'cleanup-can-private.jsonl').stat().st_size,0)
        self.assertTrue(heat.audit(worker.rows)[0]['passed'])
    def test_bad_output_stops_capture_without_retry(self):
        clock=Clock();link=Link(clock,bad=True);out=OUT/'worker-bad';out.mkdir()
        worker=d.Worker(link,NONCE,BOOT,out,clock,clock.sleep);clock.worker=worker;worker.run()
        self.assertIsNotNone(worker.error);self.assertFalse(worker.completed)
        self.assertLess(clock(),.3)
    def test_missing_heat_is_not_covered_by_regular_can(self):
        clock=Clock();link=Link(clock,no_heat=True);out=OUT/'worker-no-heat';out.mkdir()
        worker=d.Worker(link,NONCE,BOOT,out,clock,clock.sleep);clock.worker=worker;worker.run()
        self.assertIn('thermal',worker.error.lower());self.assertFalse(worker.completed)
    def test_session_boot_and_age_validation(self):
        path=OUT/'session-private.json'
        good=dict(schema_version=1,firmware_id=d.IDENTITY,prepared=True,boot=BOOT,
                  old_freeze=0,option=0x10000,prepared_at=d.time.time(),build='mock')
        with patch.object(d,'load_build',return_value=None):
            d.save(path,good);d.load_session(path,True)
            for key,value in (('prepared',False),('boot',0),('old_freeze',-1),('option',-1),('prepared_at',0)):
                s=dict(good);s[key]=value;d.save(path,s)
                with self.assertRaises(ValueError): d.load_session(path,True)
    def test_second_run_claim_cannot_reopen_probe(self):
        path=OUT/'used-session-private.json';s=dict(boot=BOOT)
        path.with_name('run-used-private.json').write_text('{}')
        with patch.object(d,'load_session',return_value=(path,s)), \
             patch.object(d,'check_can_dependencies'), \
             patch.object(d,'checked_image',side_effect=AssertionError('probe re-opened')):
            with self.assertRaises(FileExistsError):
                d.run(SimpleNamespace(allow_live=True,board_power_confirmed=True,session=str(path)))

    def flash_case(self,label,fail=None,wrong_device=False,changed_option=False):
        calls=[];binary=fake_image();hex_data=b'known test hex'
        def debug(s,commands,out,name,flash=False,pack=None):
            calls.append((name,commands))
            if name==fail: raise RuntimeError('injected '+name)
            for command in commands:
                if command.startswith('savemem'):
                    _,address,size,target=command.split(maxsplit=3)
                    size=int(size);Path(target.strip('"')).write_bytes(binary if size==d.IMAGE_BYTES else bytes(size))
            return ('Core 0 status: Halted\n40012c00:  00000000\n40012c20:  00000000\n'
                    '40012c44:  00000000\ne000e010:  00000000\ne0042008:  00000000\n'
                    f'e0042000:  {0x469 if wrong_device else 0x468:08x}\n1fff75e0:  00000080\n'
                    f'40022020:  {0x20000 if changed_option and name=="cleanup-private.txt" else 0x10000:08x}\n')
        with patch.object(d,'load_build',return_value=(manifest(),binary,hex_data)), \
             patch.object(d,'sha',return_value=d.HEX_SHA),patch.object(d,'debug',side_effect=debug), \
             patch.object(d,'read_state',return_value={'watchdog':{}}),patch.object(d.old,'healthy'):
            result=d.flash(SimpleNamespace(power_stage_disconnected=True,reset_and_halt_ack=True,
                 build='mock',output=str(OUT/label),pyocd='mock',uid='mock',pack='mock'))
        return result,calls
    def test_flash_download_failure_resets_halts_and_restores(self):
        result,calls=self.flash_case('flash-fail',fail='download-private.txt')
        self.assertFalse(result['verified']);self.assertTrue(result['core_left_halted'])
        self.assertEqual(calls[-1][0],'cleanup-private.txt')
        self.assertEqual(calls[-1][1][0],'reset halt system')
        self.assertTrue(result['debug_freeze_restored'])
        self.assertEqual(calls[1][1][0],'reset halt system')
    def test_wrong_device_has_no_reset_download_or_cleanup(self):
        result,calls=self.flash_case('flash-wrong-device',wrong_device=True)
        self.assertFalse(result['verified']);self.assertEqual(len(calls),1)
        self.assertFalse(any(c.startswith(('reset','load','ww ')) for c in calls[0][1]))
    def test_option_change_prevents_success_report(self):
        result,calls=self.flash_case('flash-option-change',changed_option=True)
        self.assertFalse(result['verified']);self.assertFalse(result['option_unchanged'])

    def runtime_case(self,label,bad_token=False,audit_error=False):
        events=[];parent=OUT/label;parent.mkdir();path=parent/'session-private.json'
        s=dict(boot=BOOT,old_freeze=0,option=0x10000)
        def debug(s,commands,out,name,*args):
            events.append(name)
            token=d.SYMBOLS['motor_td3_g431_debugger_boot_token']
            value=0 if bad_token else BOOT
            return ('Core 0 status: Halted\ne0042008:  00001000\n'+
                f'{token:08x}:  {value&0xffffffff:08x}\n{token+4:08x}:  {value>>32:08x}\n')
        class FakeLink:
            def __init__(self,*args): events.append('adapter-init')
            def close(self): events.append('adapter-close')
        class FakeWorker:
            def __init__(self,*args):
                self.holding=d.threading.Event();self.stop=d.threading.Event();self.ready=d.threading.Event()
                self.ready.set()
                self.completed=True;self.error=None;self.elapsed=3.1;self.rows=[];self.stop_seq=60;self.tx_frames=550
            def run(self): events.append('worker-start')
        class FakeThread:
            def __init__(self,target,**kwargs): self.target=target
            def start(self): self.target()
            def join(self,*args): events.append('worker-join')
            def is_alive(self): return False
        def audit(rows):
            events.append('audit')
            if audit_error: raise ValueError('injected audit failure')
            return dict(passed=True),[{}]*30
        with patch.object(d,'load_session',return_value=(path,s)),patch.object(d,'checked_image'), \
             patch.object(d,'check_can_dependencies'), \
             patch.object(d,'debug',side_effect=debug),patch.object(d,'read_state',return_value={}), \
             patch.object(d.wire,'PcanLink',FakeLink),patch.object(d,'Worker',FakeWorker), \
             patch.object(d.threading,'Thread',FakeThread),patch.object(d.heat,'audit',side_effect=audit):
            result=d.run(SimpleNamespace(allow_live=True,board_power_confirmed=True,session=str(path),
                output=str(parent/'capture'),channel='mock'))
        return result,events
    def test_runtime_halts_and_joins_before_adapter_release(self):
        result,events=self.runtime_case('runtime-good');self.assertTrue(result['verified'])
        self.assertLess(events.index('adapter-init'),events.index('resume-private.txt'))
        self.assertLess(events.index('hold-private.txt'),events.index('worker-join'))
        self.assertLess(events.index('worker-join'),events.index('adapter-close'))
    def test_audit_failure_still_releases_adapter_after_halt(self):
        result,events=self.runtime_case('runtime-audit',audit_error=True)
        self.assertFalse(result['verified']);self.assertIn('audit_error',result)
        self.assertLess(events.index('hold-private.txt'),events.index('adapter-close'))
    def test_changed_token_never_opens_can_or_resumes(self):
        result,events=self.runtime_case('runtime-token',bad_token=True)
        self.assertFalse(result['verified']);self.assertNotIn('adapter-init',events)
        self.assertNotIn('resume-private.txt',events);self.assertIn('hold-private.txt',events)


def main():
    global OUT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    args=p.parse_args();OUT=d.fresh(args.output)
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EntryTests))
    summary=dict(schema_version=1,tests=r.testsRun,passed=r.wasSuccessful(),failures=len(r.failures),errors=len(r.errors),
        scope='hardware entry/worker checks with software substitutes',hardware_accessed=False,
        thermal_protection_verified=False,motion_approved=False,
        sources_sha256={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest()
                        for n in ('thermal_diagnostic.py','test_thermal_diagnostic.py','build_speedloop_diagnostic.py')})
    d.save(OUT/'summary.json',summary);print(json.dumps(summary))
    if not r.wasSuccessful(): raise SystemExit(1)


if __name__=='__main__': main()
