"""ADC observation safety contract, nominal math and error cleanup, no hardware."""
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
import g431_current_zero as diag

OUTPUT=None
def fixture():
    data=struct.pack('<II',diag.pil.STACK_TOP,diag.pil.RAM+513)+bytes(632)
    c=dict(schema_version=1,mode=diag.MODE,expected_cases=7,expected_samples=64,entry=diag.pil.RAM+513,
        load_address=diag.pil.RAM,mailbox_address=diag.pil.MAILBOX,rows_address=diag.ROWS_ADDRESS,
        stack_bottom=diag.pil.STACK_BOTTOM,stack_top=diag.pil.STACK_TOP,
        image_bytes=len(data),image_sha256=diag.pil.sha(data),source_sha256=diag.source_hashes(),
        **{k:False for k in diag.FALSE_FLAGS})
    m={k:0 for k in diag.FIELDS}
    m.update(magic=0x435A5231,schema=1,state=2,cases=7,passed=7,samples=64,cycles=500000,
        adc1_calfact=40,adc2_calfact=42,adc_common=0x30000,adc1_smpr1=0xC00,adc1_smpr2=0x180,
        adc2_smpr1=0xC00,opamp1_csr=0x12980001,opamp2_csr=0x13980001,opamp3_csr=0x12780001,
        gpioa_phase_mode=0x3F0000,gpiob_phase_mode=0xFC000000,last_adc1_isr=11,last_adc2_isr=11)
    rows=[dict(a=2044+i%2,b=2040,c=2034,safe=1) for i in range(64)]
    return c,data,m,rows

def pack(m,rows):
    return struct.pack('<'+'I'*len(diag.FIELDS),*(m[k] for k in diag.FIELDS)),b''.join(
        struct.pack('<IIII',*(r[k] for k in diag.ROW_FIELDS)) for r in rows)

def reports():
    import g431_comp_break as comp_diag
    import test_g431_comp_break as comp_test
    _,_,m,rows=fixture();_,_,cm,cr=comp_test.fixture()
    zero=dict(mode=diag.MODE,verified=True,flash_unchanged=True,core_left_halted=True,
        mailbox=m,trace=rows,**{k:False for k in diag.FALSE_FLAGS})
    comp=dict(mode=comp_diag.MODE,verified=True,current_threshold_calibrated=False,
        flash_unchanged=True,core_left_halted=True,mailbox=cm,
        trace=[dict(zip(comp_diag.ROW_FIELDS,r)) for r in cr],
        **{k:False for k in comp_diag.FALSE_FLAGS})
    return zero,comp

class Contract(unittest.TestCase):
    def test_valid_fixed_image_and_trace(self):
        c,data,m,rows=fixture();diag.validate(c,data);diag.analyze(*pack(m,rows))
    def test_missing_confirmation_before_files_or_probe(self):
        with patch.object(diag.pil,'session',side_effect=AssertionError('Probe opened')):
            for power,ack in [(False,True),(True,False)]:
                with self.assertRaises(ValueError):diag.run(SimpleNamespace(power_stage_disconnected=power,power_stage_connected=False,pwm_disabled_ack=False,reset_and_halt_ack=ack))
        with self.assertRaises(ValueError):diag.run(SimpleNamespace(power_stage_disconnected=False,power_stage_connected=True,pwm_disabled_ack=False,reset_and_halt_ack=True))
    def test_image_flash_entry_and_stack_layout_rejected(self):
        c,data,_,_=fixture()
        with self.assertRaises(ValueError):diag.validate(c,data[:-1]+b'x')
        for key,value in [('entry',0x08000101),('stack_top',0x20008000),('expected_samples',65)]:
            wrong=copy.deepcopy(c);wrong[key]=value
            with self.assertRaises(ValueError):diag.validate(wrong,data)
    def test_motion_threshold_write_and_source_change_rejected(self):
        c,data,_,_=fixture()
        for k in diag.FALSE_FLAGS:
            wrong=copy.deepcopy(c);wrong[k]=True
            with self.assertRaises(ValueError):diag.validate(wrong,data)
        c['source_sha256']['stm32_g431_current_zero.c']='0'*64
        with self.assertRaises(ValueError):diag.validate(c,data)
    def test_pwm_pin_and_sample_isolation_rejected(self):
        for key,value in [('tim_bdtr',0x8000),('gpioa_phase_mode',0),('unsafe_samples',1)]:
            _,_,m,rows=fixture();m[key]=value
            with self.assertRaises(ValueError):diag.analyze(*pack(m,rows))
        _,_,m,rows=fixture();rows[5]['safe']=0
        with self.assertRaises(ValueError):diag.analyze(*pack(m,rows))
    def test_overrun_clock_and_calibration_failure_rejected(self):
        for key,value in [('last_adc1_isr',0x10),('adc_common',0),('adc2_calfact',128),('error',2)]:
            _,_,m,rows=fixture();m[key]=value
            with self.assertRaises(ValueError):diag.analyze(*pack(m,rows))
    def test_incomplete_or_non12bit_trace_rejected(self):
        _,_,m,rows=fixture();raw,trace=pack(m,rows)
        with self.assertRaises(ValueError):diag.analyze(raw,trace[:-1])
        rows[3]['b']=4096
        with self.assertRaises(ValueError):diag.analyze(*pack(m,rows))
    def test_statistics_preserve_fractional_mean_and_population_noise(self):
        _,_,_,rows=fixture();s=diag.zero_statistics(rows)
        self.assertEqual(s['a']['mean_adc'],2044.5);self.assertEqual(s['a']['stddev_counts'],.5)
        self.assertEqual(s['c']['stddev_counts'],0);self.assertEqual(s['a']['span_counts'],1)
    def test_factory_trim_and_status_are_not_configuration_errors(self):
        _,_,m,rows=fixture();m['opamp1_csr']|=0x40000000
        diag.analyze(*pack(m,rows))
    def test_user_trim_or_wrong_opamp_routing_rejected(self):
        for bit in (0x10,0x20,0x80000000):
            _,_,m,rows=fixture();m['opamp3_csr']|=bit
            with self.assertRaises(ValueError):diag.analyze(*pack(m,rows))

class Planning(unittest.TestCase):
    def test_nominal_math_never_approves_or_writes(self):
        p=diag.nominal_plan(*reports())
        self.assertFalse(p['device_write']);self.assertFalse(p['motor_control_approved'])
        self.assertFalse(p['current_gain_calibrated']);self.assertFalse(p['current_threshold_calibrated'])
        self.assertAlmostEqual(p['existing_dac3000_nominal_positive_current_a'][0],20.91796875)
        self.assertEqual(p['illustrative_positive_3a']['nearest_ideal_code'],2184)
    def test_existing_failed_or_energized_report_rejected(self):
        zero,comp=reports()
        for key in ('verified','flash_unchanged','core_left_halted'):
            bad=copy.deepcopy(zero);bad[key]=False
            with self.assertRaises(ValueError):diag.nominal_plan(bad,comp)
        zero['motor_output']=True
        with self.assertRaises(ValueError):diag.nominal_plan(zero,comp)
    def test_missing_crossing_or_bad_adc_trace_rejected(self):
        zero,comp=reports();comp['mailbox']['transition_high']+=1
        with self.assertRaises(ValueError):diag.nominal_plan(zero,comp)
        zero,comp=reports();zero['trace'][5]['a']=4096
        with self.assertRaises(ValueError):diag.nominal_plan(zero,comp)
    def test_adc_rails_are_reported_and_plan_refused(self):
        zero,comp=reports();zero['trace'][4]['b']=0
        self.assertEqual(diag.zero_statistics(zero['trace'])['b']['rail_samples'],1)
        with self.assertRaises(ValueError):diag.nominal_plan(zero,comp)

class FakeTarget:
    def __init__(self,raw,trace,flash_changed=False,initial_unsafe=False):
        self.raw=raw;self.trace=trace;self.resets=0;self.resumes=0;self.writes=[];self.image=None
        self.flash_changed=flash_changed;self.initial_unsafe=initial_unsafe
        self.selected_core=SimpleNamespace(write_core_registers_raw=lambda *args:None)
    def halt(self):pass
    def get_state(self):return 'halted'
    def reset_and_halt(self,*args):self.resets+=1
    def resume(self):self.resumes+=1
    def read_memory_block8(self,address,n):
        if address==diag.pil.FLASH:return bytes([int(self.flash_changed and self.resumes>0)])*n
        if address==diag.pil.RAM:return self.image
        if address==diag.pil.MAILBOX:return self.raw
        if address==diag.ROWS_ADDRESS:return self.trace
        return bytes([0xA5])*n
    def write_memory_block8(self,address,data):
        self.writes.append(address)
        if address==diag.pil.RAM:self.image=bytes(data)
    def write32(self,*args):pass

class Cleanup(unittest.TestCase):
    def run_fake(self,name,invalid=False,flash_changed=False,initial_unsafe=False):
        c,data,m,rows=fixture()
        if invalid:rows[5]['safe']=0
        t=FakeTarget(*pack(m,rows),flash_changed=flash_changed,initial_unsafe=initial_unsafe)
        build=OUTPUT/(name+'-build');build.mkdir()
        (build/'build-summary.json').write_text(json.dumps(c),encoding='utf-8');(build/'current-zero.bin').write_bytes(data)
        session=SimpleNamespace(target=t,open=lambda:None,close=lambda:None)
        mock=types.ModuleType('pyocd.core.target')
        mock.Target=SimpleNamespace(State=SimpleNamespace(HALTED='halted',RUNNING='running'),ResetType=SimpleNamespace(SYSRESETREQ=1))
        modules={k:types.ModuleType(k) for k in ('pyocd','pyocd.core')};modules['pyocd.core.target']=mock
        def safe(target):return dict(tim1_cr1=0,tim1_ccer=0,tim1_bdtr=int(target.initial_unsafe and target.resets==1),gpio_clocks=0)
        with patch.dict(sys.modules,modules),patch.object(diag.pil,'session',return_value=session),\
            patch.object(diag.pil,'identity',return_value={'mock':True}),patch.object(diag,'safe_registers',side_effect=safe):
            r=diag.run(SimpleNamespace(build=str(build),output=str(OUTPUT/name),power_stage_disconnected=True,power_stage_connected=False,pwm_disabled_ack=False,reset_and_halt_ack=True))
        self.assertTrue(r['core_left_halted']);self.assertFalse(r['original_application_resumed'])
        self.assertEqual(t.resets,2);self.assertNotIn(diag.pil.FLASH,t.writes)
        return r,t
    def test_success_preserves_flash_and_leaves_halted(self):
        r,t=self.run_fake('success');self.assertTrue(r['verified']);self.assertEqual(t.resumes,1)
    def test_bad_trace_still_resets_and_halts(self):
        r,_=self.run_fake('bad-trace',invalid=True);self.assertFalse(r['verified']);self.assertTrue(r['flash_unchanged'])
    def test_flash_change_fails_result(self):
        r,_=self.run_fake('flash-change',flash_changed=True);self.assertFalse(r['verified']);self.assertFalse(r['flash_unchanged'])
    def test_unsafe_initial_never_loads_or_resumes(self):
        r,t=self.run_fake('unsafe-initial',initial_unsafe=True)
        self.assertFalse(r['verified']);self.assertEqual(t.resumes,0);self.assertEqual(t.writes,[])

def main():
    global OUTPUT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    OUTPUT=diag.pil.fresh_dir(a.output)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Contract,Planning,Cleanup)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    diag.pil.save_json(OUTPUT/'summary.json',dict(schema_version=1,tests=r.testsRun,passed=r.wasSuccessful(),
        failures=len(r.failures),errors=len(r.errors),hardware_accessed=False))
    if not r.wasSuccessful():raise SystemExit(1)

if __name__=='__main__':main()
