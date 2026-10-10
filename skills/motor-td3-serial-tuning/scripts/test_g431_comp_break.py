"""Diagnostic contract, physical-trace rejection and cleanup tests; no hardware."""
import argparse
import copy
import json
import struct
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import g431_comp_break as diag

OUTPUT=None
def fixture():
    data=struct.pack('<II',diag.pil.STACK_TOP,diag.pil.RAM+513)+bytes(632)
    c=dict(schema_version=1,mode=diag.MODE,expected_cases=8,entry=diag.pil.RAM+513,
        load_address=diag.pil.RAM,mailbox_address=diag.pil.MAILBOX,
        stack_bottom=diag.pil.STACK_BOTTOM,stack_top=diag.pil.STACK_TOP,rows_address=diag.ROWS_ADDRESS,
        image_bytes=len(data),image_sha256=diag.pil.sha(data),source_sha256=diag.source_hashes(),
        **{k:False for k in diag.FALSE_FLAGS})
    m={k:0 for k in diag.FIELDS}
    m.update(magic=0x43425231,schema=1,state=2,cases=8,passed=8,fault_latched=1,
        samples=17,cycles=380000,comp_config=0x141,dac_mode=3,tim_route=2,
        tim_break_config=0x23078,gpioa_phase_mode=0x3F0000,gpiob_phase_mode=0xFC000000,
        recovery_latch=1)
    def row(code,flag): return [code,0x141|(0x40000000 if code<2048 else 0),flag,1]
    rows=[row(4095,0),row(3000,0),row(0,128),row(4095,128)]
    lo,hi=0,4095
    for _ in range(12):
        mid=(lo+hi)//2;rows.append(row(mid,128))
        if mid<2048: lo=mid
        else: hi=mid
    m.update(transition_low=lo,transition_high=hi);rows.append(row(4095,128))
    return c,data,m,rows

def pack(m,rows):
    return struct.pack('<'+'I'*len(diag.FIELDS),*(m[k] for k in diag.FIELDS)),b''.join(struct.pack('<IIII',*r) for r in rows)

class Contract(unittest.TestCase):
    def test_fixed_image_and_trace_valid(self):
        c,data,m,rows=fixture();diag.validate(c,data);diag.analyze(*pack(m,rows))
    def test_missing_power_confirmation_before_files_or_probe(self):
        with patch.object(diag.pil,'session',side_effect=AssertionError('Probe opened')):
            for power,ack in [(False,True),(True,False)]:
                with self.assertRaises(ValueError): diag.run(SimpleNamespace(power_stage_disconnected=power,reset_and_halt_ack=ack))
    def test_changed_image_or_flash_entry_rejected(self):
        c,data,_,_=fixture()
        with self.assertRaises(ValueError): diag.validate(c,data[:-1]+b'x')
        c['entry']=0x08000101
        with self.assertRaises(ValueError): diag.validate(c,data)
    def test_motion_or_wrong_source_rejected(self):
        c,data,_,_=fixture()
        for k in diag.FALSE_FLAGS:
            wrong=copy.deepcopy(c);wrong[k]=True
            with self.assertRaises(ValueError): diag.validate(wrong,data)
        c['source_sha256']['motor_td3_g431_off.h']='0'*64
        with self.assertRaises(ValueError): diag.validate(c,data)
    def test_no_real_bif_rejected(self):
        _,_,m,rows=fixture();rows[2][2]=0
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
    def test_comparator_does_not_change_rejected(self):
        _,_,m,rows=fixture();rows[2][1]&=~0x40000000
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
    def test_moe_or_phase_isolation_failed_rejected(self):
        _,_,m,rows=fixture();rows[8][3]=0
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
        _,_,m,rows=fixture();m['tim_bdtr']=0x8000
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
    def test_recovery_clears_software_latch_rejected(self):
        _,_,m,rows=fixture();m['recovery_latch']=0
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
    def test_reversed_route_or_auto_restore_rejected(self):
        for k,v in [('tim_route',0x402),('tim_break_config',0x27078)]:
            _,_,m,rows=fixture();m[k]=v
            with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
    def test_false_transition_or_truncated_trace_rejected(self):
        _,_,m,rows=fixture();m['transition_low']-=1
        with self.assertRaises(ValueError): diag.analyze(*pack(m,rows))
        _,_,m,rows=fixture();raw,trace=pack(m,rows)
        with self.assertRaises(ValueError): diag.analyze(raw,trace[:-1])

class FakeTarget:
    def __init__(self,raw,trace,flash_changed=False,initial_unsafe=False):
        self.raw=raw;self.trace=trace;self.resets=0;self.resumes=0;self.halts=0;self.writes=[]
        self.flash_changed=flash_changed;self.initial_unsafe=initial_unsafe;self.image=None
        self.selected_core=SimpleNamespace(write_core_registers_raw=lambda *args:None)
    def halt(self): self.halts+=1
    def get_state(self): return 'halted'
    def reset_and_halt(self,*args): self.resets+=1
    def resume(self): self.resumes+=1
    def read_memory_block8(self,address,n):
        if address==diag.pil.FLASH: return bytes([1 if self.flash_changed and self.resumes else 0])*n
        if address==diag.pil.RAM: return self.image
        if address==diag.pil.MAILBOX: return self.raw
        if address==diag.ROWS_ADDRESS: return self.trace
        return bytes([0xA5])*n
    def write_memory_block8(self,address,data):
        self.writes.append(address)
        if address==diag.pil.RAM: self.image=bytes(data)
    def write32(self,*args): pass

class Cleanup(unittest.TestCase):
    def run_fake(self,name,invalid=False,flash_changed=False,initial_unsafe=False):
        c,data,m,rows=fixture()
        if invalid: rows[2][2]=0
        target=FakeTarget(*pack(m,rows),flash_changed=flash_changed,initial_unsafe=initial_unsafe)
        build=OUTPUT/(name+'-build');build.mkdir()
        (build/'build-summary.json').write_text(json.dumps(c),encoding='utf-8');(build/'comp-break.bin').write_bytes(data)
        session=SimpleNamespace(target=target,open=lambda:None,close=lambda:None)
        mock=types.ModuleType('pyocd.core.target')
        mock.Target=SimpleNamespace(State=SimpleNamespace(HALTED='halted',RUNNING='running'),ResetType=SimpleNamespace(SYSRESETREQ=1))
        def safe(t):
            return {'tim1_cr1':0,'tim1_ccer':0,'tim1_bdtr':int(t.initial_unsafe and t.resets==1),'gpio_clocks':0}
        modules={key:types.ModuleType(key) for key in ('pyocd','pyocd.core')};modules['pyocd.core.target']=mock
        with patch.dict(sys.modules,modules),patch.object(diag.pil,'session',return_value=session),\
            patch.object(diag.pil,'identity',return_value={'mock':True}),patch.object(diag,'safe_registers',side_effect=safe):
            r=diag.run(SimpleNamespace(build=str(build),output=str(OUTPUT/name),power_stage_disconnected=True,reset_and_halt_ack=True))
        self.assertTrue(r['core_left_halted']);self.assertFalse(r['original_application_resumed'])
        self.assertEqual(target.resets,2);self.assertNotIn(diag.pil.FLASH,target.writes)
        return r,target
    def test_success_resets_and_preserves_flash(self):
        r,t=self.run_fake('success');self.assertTrue(r['verified']);self.assertEqual(t.resumes,1)
    def test_bad_trace_still_resets_and_halts(self):
        r,_=self.run_fake('bad-trace',invalid=True);self.assertFalse(r['verified']);self.assertTrue(r['flash_unchanged'])
    def test_flash_difference_cannot_pass(self):
        r,_=self.run_fake('flash-difference',flash_changed=True);self.assertFalse(r['verified']);self.assertFalse(r['flash_unchanged'])
    def test_initial_unsafe_never_loads_or_resumes(self):
        r,t=self.run_fake('unsafe-initial',initial_unsafe=True)
        self.assertFalse(r['verified']);self.assertEqual(t.resumes,0);self.assertEqual(t.writes,[])

def main():
    global OUTPUT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    OUTPUT=diag.pil.fresh_dir(a.output)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Contract,Cleanup)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    diag.pil.save_json(OUTPUT/'summary.json',dict(schema_version=1,tests=r.testsRun,passed=r.wasSuccessful(),
        failures=len(r.failures),errors=len(r.errors),hardware_accessed=False))
    if not r.wasSuccessful(): raise SystemExit(1)

if __name__=='__main__': main()
