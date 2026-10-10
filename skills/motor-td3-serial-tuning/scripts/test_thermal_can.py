"""C encoder, locked adapter and offline CAN thermal audits; no hardware access."""
import argparse
import copy
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import unittest
import zlib
import can_transport as wire
import thermal_can as heat
import build_speedloop_diagnostic as builder
import test_g431_integration as adapter_test

LIB = ADAPTER = None
BOOT = 0x1234567812345678


def packet(case=2):
    out = ct.create_string_buffer(144)
    assert LIB.test_heat_case(out, case) == 144
    return out.raw


def change(data, offset, fmt, value):
    data = bytearray(data); struct.pack_into(fmt, data, offset, value)
    struct.pack_into('<I', data, 140, zlib.crc32(data[:140])); return bytes(data)


def fragments(data, tag=1):
    return [bytes([0xD1, tag, i//4, len(data)])+data[i:i+4] for i in range(0, len(data), 4)]


def row(identifier, data, now):
    return dict(host_monotonic_s=now, arbitration_id=identifier, dlc=8, data_hex=data.hex(),
                extended=False, remote=False, error=False, status_frame=False, fd=False)


def hello_rows(firmware=heat.FIRMWARE, boot=BOOT, capabilities=0):
    data = wire.pack(dict(type='hello_reply', firmware_id=firmware, profile_id=firmware,
                         capabilities=[c for i,c in enumerate(wire.CAPABILITIES) if capabilities & (1<<i)]), 7, boot)
    return [row(0x621, f, i*.0001) for i, f in enumerate(wire.fragment(data, 1))]


def rows(data=None, **kwargs):
    prefix = hello_rows(**kwargs)
    return prefix+[row(heat.CAN_ID, f, .01+i*.0001) for i, f in enumerate(fragments(data or packet()))]


class Codec(unittest.TestCase):
    def test_c_invalid_arguments(self): self.assertEqual(LIB.test_heat_arguments(), 1)
    def test_missing_calibration_is_unknown_not_cold(self):
        s=heat.unpack(packet(0));self.assertEqual(s['feed_fault'], 'calibration')
        self.assertEqual(s['used_a2s'], [None]*3);self.assertIsNone(s['energized_us'])
        self.assertIsNone(s['temperature_c']);self.assertFalse(s['motion_approved'])
    def test_unknown_seed_after_verified_limits(self):
        s=heat.unpack(packet(1));self.assertTrue(s['limits_verified'])
        self.assertEqual(s['thermal_fault'], 'boot_unknown');self.assertEqual(s['phase_load'], [None]*3)
    def test_real_core_accounting_and_ieee64_parity(self):
        s=heat.unpack(packet());self.assertTrue(s['window_fresh_at_capture'])
        self.assertAlmostEqual(s['used_a2s'][0], .013104, places=7)
        self.assertEqual(s['energized_us'], 10000);self.assertEqual(s['sample_seq'], 2)
        self.assertFalse(s['training_telemetry']);self.assertTrue(s['motion_inhibited'])
    def test_budget_exhaustion(self):
        s=heat.unpack(packet(3));self.assertEqual(s['thermal_fault'], 'budget')
        self.assertEqual(s['phase_load'][0], 1);self.assertTrue(s['block_reasons'])
    def test_stale_feed(self):
        s=heat.unpack(packet(4));self.assertEqual(s['feed_fault'], 'stale')
        self.assertFalse(s['sample_fresh_at_capture'])
    def test_already_hot_seed_keeps_known_budget(self):
        s=heat.unpack(packet(5));self.assertTrue(s['initial_heat_known'])
        self.assertEqual(s['used_a2s'][0], 1);self.assertEqual(s['thermal_fault'], 'budget')
    def test_partial_bad_seed_never_leaks_as_known(self):
        s=heat.unpack(packet(6));self.assertEqual(s['used_a2s'], [None]*3)
    def test_sampled_peak_before_window(self):
        s=heat.unpack(packet(7));self.assertEqual(s['feed_fault'], 'peak');self.assertEqual(s['window_seq'], 0)
    def test_zero_heat_is_distinct_from_unknown(self):
        s=heat.unpack(packet(8));self.assertEqual(s['used_a2s'], [0]*3)
        self.assertTrue(s['initial_heat_known']);self.assertIsNone(s['temperature_c'])
    def test_bad_crc_and_version(self):
        bad=bytearray(packet());bad[84]^=1
        for data in (bad, change(packet(), 4, '<B', 2), packet()[:-1]):
            with self.assertRaises(heat.DiagnosticError): heat.unpack(data)
    def test_invalid_flags_and_faults(self):
        for offset, fmt, value in ((28,'<I',512),(32,'<H',99),(34,'<H',99),(5,'<B',1)):
            with self.assertRaises(heat.DiagnosticError): heat.unpack(change(packet(),offset,fmt,value))
    def test_nan_negative_and_unknown_zero_refused(self):
        for data in (change(packet(),76,'<d',float('nan')),change(packet(),76,'<d',-1),
                     change(packet(),76,'<d',1.7e308),
                     change(packet(),100,'<f',0),change(packet(0),76,'<d',0)):
            with self.assertRaises(heat.DiagnosticError): heat.unpack(data)
    def test_false_freshness_and_future_sample(self):
        for data in (change(packet(),36,'<Q',20000),change(packet(),52,'<Q',11000)):
            with self.assertRaises(heat.DiagnosticError): heat.unpack(data)
    def test_normal_audit_json_has_no_nan(self):
        summary,snapshots=heat.audit(rows());self.assertTrue(summary['passed'])
        self.assertEqual(len(snapshots),1);json.dumps(summary,allow_nan=False)
        self.assertFalse(summary['thermal_protection_verified'])
    def test_no_valid_hello_wrong_identity_capability_or_boot(self):
        for source in (rows()[len(hello_rows()):],rows(firmware='g431-speedloop-wdog-v1'),
                       rows(capabilities=1),rows(boot=BOOT+1)):
            self.assertFalse(heat.audit(source)[0]['passed'])
    def test_training_protocol_rejects_thermal_datagram(self):
        with self.assertRaises(wire.WireError): wire.unpack(packet())
    def test_classic_type_required(self):
        for field in ('extended','remote','error','status_frame','fd'):
            source=rows();source[-1][field]=True
            self.assertFalse(heat.audit(source)[0]['passed'])
    def test_bus_error_event_outside_diagnostic_id(self):
        source=rows()+[dict(row(0,b'\0'*8,.02),error=True)]
        self.assertFalse(heat.audit(source)[0]['passed'])
    def test_gap_duplicate_reordered_mixed_transfer_and_truncation(self):
        source=rows();start=len(hello_rows())
        variants=[source[:start+8]+source[start+9:],source[:start+8]+[source[start+7]]+source[start+8:],
                  source[:-1]]
        mixed=copy.deepcopy(source);frame=bytearray.fromhex(mixed[start+4]['data_hex']);frame[1]=2
        mixed[start+4]['data_hex']=frame.hex();variants.append(mixed)
        for variant in variants: self.assertFalse(heat.audit(variant)[0]['passed'])
    def test_matching_tag_mixed_snapshot_crc_refused(self):
        first,second=packet(),packet(0);mixed=fragments(first)
        mixed[20:]=fragments(second)[20:]
        source=hello_rows()+[row(heat.CAN_ID,f,.01+i*.0001) for i,f in enumerate(mixed)]
        self.assertFalse(heat.audit(source)[0]['passed'])
    def test_fragment_deadline_and_host_clock_reversal(self):
        for stamp in (.1, .0001):
            source=rows();source[-1]['host_monotonic_s']=stamp
            self.assertFalse(heat.audit(source)[0]['passed'])
    def test_replay_and_wrong_nonce_refused(self):
        for data in (packet(),change(packet(),8,'<Q',8)):
            source=rows()+[row(heat.CAN_ID,f,.03+i*.0001) for i,f in enumerate(fragments(data,2))]
            self.assertFalse(heat.audit(source)[0]['passed'])
    def test_cumulative_heat_and_fault_cannot_clear(self):
        for first,second in ((packet(),packet(8)),(packet(3),packet(2)),
                             (packet(),change(packet(),52,'<Q',9999))):
            second=change(second,24,'<I',2)
            source=rows(first)+[row(heat.CAN_ID,f,.03+i*.0001) for i,f in enumerate(fragments(second,2))]
            self.assertFalse(heat.audit(source)[0]['passed'])
    def test_contiguous_snapshots_and_missing_complete_packet(self):
        for seq,passed in ((2,True),(3,False)):
            source=rows()+[row(heat.CAN_ID,f,.03+i*.0001) for i,f in enumerate(fragments(change(packet(),24,'<I',seq),2))]
            self.assertEqual(heat.audit(source)[0]['passed'],passed)
    def test_boot_change_requires_separate_capture(self):
        source=rows()+[dict(r,host_monotonic_s=.03+i*.0001) for i,r in enumerate(hello_rows(boot=BOOT+1))]
        self.assertFalse(heat.audit(source)[0]['passed'])


class LockedAdapter(unittest.TestCase):
    def setUp(self):
        ADAPTER.test_heat_reset();ADAPTER.test_boot(BOOT)
    def hello(self):
        for f in wire.fragment(wire.pack(dict(type='hello',profile_id=heat.FIRMWARE),7),1):
            ADAPTER.test_feed(f,0)
        ADAPTER.test_poll();ADAPTER.test_ticks(1);ADAPTER.test_adc();ADAPTER.test_poll()
    def drain(self):
        for _ in range(130): ADAPTER.test_poll()
    def raw(self):
        result=[]
        for i in range(ADAPTER.test_count()):
            f=ct.create_string_buffer(8);identifier=ADAPTER.test_sent(i,f)
            result.append(row(identifier,f.raw,i*.00001))
        return result
    def test_actual_private_adapter_hello_first_zero_capability_and_coherent_heat(self):
        self.hello();self.drain();raw=self.raw();ids=[r['arbitration_id'] for r in raw]
        self.assertTrue(0x626 in ids and 0x622 in ids);self.assertEqual(ids[0],0x621)
        summary,_=heat.audit(raw);self.assertTrue(summary['passed'])
        self.assertEqual(summary['latest']['feed_fault'],'calibration');self.assertTrue(ADAPTER.test_off())
    def test_heat_waits_for_actual_tx_event_and_keeps_foreground_polling(self):
        ADAPTER.test_tx_hold(1);self.hello();self.drain();self.assertEqual(ADAPTER.test_count(),1)
        ADAPTER.test_tx_hold(0);self.drain()
        self.assertTrue(heat.audit(self.raw())[0]['passed']);self.assertTrue(ADAPTER.test_off())
    def test_frozen_packet_does_not_mix_fault_change_between_fragments(self):
        self.hello()
        for _ in range(100):
            ADAPTER.test_poll()
            if any(r['arbitration_id']==0x626 for r in self.raw()): break
        ADAPTER.test_heat_change_fault();self.drain()
        summary,_=heat.audit(self.raw());self.assertTrue(summary['passed'])
        self.assertEqual(summary['latest']['feed_fault'],'calibration')
    def test_missing_ack_on_heat_latches_timeout(self):
        self.hello()
        for _ in range(100):
            ADAPTER.test_poll()
            if any(r['arbitration_id']==0x626 for r in self.raw()): break
        ADAPTER.test_tx_hold(1)
        for _ in range(51): ADAPTER.test_ticks(1);ADAPTER.test_adc();ADAPTER.test_poll()
        self.assertTrue(ADAPTER.test_fault());self.assertTrue(ADAPTER.test_off())
        self.assertFalse(heat.audit(self.raw())[0]['passed'])


def main():
    global LIB,ADAPTER
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--compiler',default='gcc');args=p.parse_args();out=Path(args.output).resolve()
    if os.name=='nt' and Path(r'E:\simulink\_codex_tmp').resolve() not in out.parents:
        raise ValueError('Windows test output must be under the approved temp root')
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh task directory')
    out.mkdir(parents=True,exist_ok=True);fw=Path(__file__).resolve().parents[1]/'firmware'
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    common=[args.compiler,'-shared','-fPIC','-std=c99','-O2','-pipe','-Wall','-Wextra','-Werror',
            '-fno-fast-math','-ffp-contract=off','-I',str(out),'-I',str(fw)]
    ext='.dll' if os.name=='nt' else '.so'
    def compile(name,sources,defines=()):
        target=out/(name+ext)
        r=subprocess.run([*common,*defines,*map(str,sources),'-lm','-o',str(target)],env=env,capture_output=True,text=True)
        (out/(name+'-build.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode: raise RuntimeError('Compile failed: '+name+'-build.log')
        return ct.CDLL(str(target))
    modules=['motor_td3_thermal.c','motor_td3_thermal_feed.c','motor_td3_thermal_can.c']
    LIB=compile('codec',[fw/s for s in modules]+[fw/'tests/thermal_can_host.c'])
    for name in ('stm32g431xx.h','main.h','fdcan.h','FOC_Model.h'):
        (out/name).write_text(adapter_test.STUB,encoding='ascii')
    # Compile precisely the private adapter used by the real full-project builder.
    (out/'motor_td3_g431_adapter.c').write_text(builder.patch_thermal_adapter((fw/'motor_td3_g431_adapter.c').read_text(encoding='utf-8')),encoding='utf-8')
    fixture=(fw/'tests/g431_adapter_host.c').read_text(encoding='utf-8')+'''
#include "motor_td3_speedloop_thermal.h"
uint16_t adc1_in1,adc1_in2,adc1_in3;
volatile uint32_t motor_td3_speedloop_sample_count,motor_td3_speedloop_sample_errors;
void test_heat_reset(void) {
    test_reset();heat_length=heat_index=heat_sequence=heat_transfer=0;heat_started_us=heat_due_us=0;
    memset(&motor_td3_speedloop_thermal_state,0,sizeof(motor_td3_speedloop_thermal_state));
    motor_td3_speedloop_thermal_init();
}
void test_heat_change_fault(void) { motor_td3_speedloop_thermal_state.fault=TD3_FEED_PEAK; }
'''
    (out/'adapter_host.c').write_text(fixture,encoding='utf-8')
    extra=['motor_td3_can.c','motor_td3_can_control.c','motor_td3_guard.c',
           'motor_td3_health.c','motor_td3_g431_watchdog.c','motor_td3_speedloop_thermal.c']
    ADAPTER=compile('adapter',[out/'adapter_host.c']+[fw/s for s in modules+extra],
                    ['-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC','-DMOTOR_TD3_SPEEDLOOP_WATCHDOG'])
    ADAPTER.test_boot.argtypes=[ct.c_uint64]
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Codec,LockedAdapter)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(schema_version=1,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                 passed=result.wasSuccessful(),hardware_accessed=False,thermal_protection_verified=False,
                 motion_approved=False,firmware_id=heat.FIRMWARE,packet_bytes=144,can_id='0x626',
                 encoder_snapshot_nonmutating=True,
                 tool_sha256={s:hashlib.sha256((Path(__file__).parent/s).read_bytes()).hexdigest()
                              for s in ('thermal_can.py','test_thermal_can.py','build_speedloop_diagnostic.py')},
                 source_sha256={s:hashlib.sha256((fw/s).read_bytes()).hexdigest() for s in modules+extra+['motor_td3_thermal.h','motor_td3_thermal_can.h','tests/thermal_can_host.c']})
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    # Formal example is explicitly synthetic, generated through the real C feed.
    demo=rows(packet(0));report,_=heat.audit(demo)
    (out/'example-raw.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in demo),encoding='utf-8')
    report.update(evidence_origin='software-only C feed and synthetic CAN frames; not board readings')
    (out/'example-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(summary))
    if not result.wasSuccessful(): raise SystemExit(1)


if __name__=='__main__': main()
