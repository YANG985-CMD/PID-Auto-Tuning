"""Supervisor C and watchdog SRAM contract checks; no hardware access."""
import argparse
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
import unittest
import g431_watchdog_pil as pil


class Contract(unittest.TestCase):
    def setUp(self):
        self.data=struct.pack('<II',pil.STACK,pil.RAM+513)+bytes(632)
        self.contract=dict(schema_version=1,mode=pil.MODE,entry=pil.RAM+513,stack_top=pil.STACK,
                           load_address=pil.RAM,mailbox_address=pil.MAILBOX,image_bytes=len(self.data),
                           image_sha256=pil.sha(self.data),source_sha256=pil.hashes(),
                           flash_programming=False,option_programming=False,motor_output=False,
                           external_can=False,software_iwdg_start=True)
        self.box=dict.fromkeys(pil.FIELDS,0)
        self.box.update(magic=0x57444731,schema=1,mode=1,stage=2,feeds=60,irq_ticks=800,
                        irq_at_starve=600,healthy_cycles=9601000,spin_cycles=3200000,
                        dbg_during=0xC060083F,option_before=0xFBEFF8AA,gpioa_phase=0x3F0000,
                        gpiob_phase=0xFC000000,iwdg_pr=3,iwdg_rlr=199,iwdg_winr=4095)
        self.reset_vector=0x080001D9
        self.trace=('Core 0 (None):  Halted\npc = 0x080001d8\nxpsr = 0x01000000\n'
                    '40021094:  20000003\n40022020:  fbeff8aa\n'
                    '40012c00:  00000000\n40012c20:  00000000\n40012c44:  00000000\n')

    def raw(self):
        return struct.pack('<'+'I'*len(pil.FIELDS),*(self.box[n] for n in pil.FIELDS))

    def test_valid_contract(self):
        pil.validate(self.contract,self.data)

    def test_missing_power_confirmation_before_file_or_probe_access(self):
        with self.assertRaises(ValueError):
            pil.run(SimpleNamespace(power_stage_disconnected=False,reset_and_halt_ack=True))
        with self.assertRaises(ValueError):
            pil.run(SimpleNamespace(power_stage_disconnected=True,reset_and_halt_ack=False))

    def test_unsafe_or_changed_image_refused(self):
        for name in ('flash_programming','option_programming','motor_output','external_can'):
            c=copy.deepcopy(self.contract);c[name]=True
            with self.subTest(name=name),self.assertRaises(ValueError): pil.validate(c,self.data)
        with self.assertRaises(ValueError): pil.validate(self.contract,self.data[:-1]+b'x')
        c=copy.deepcopy(self.contract);c['source_sha256']={}
        with self.assertRaises(ValueError): pil.validate(c,self.data)

    def test_both_interrupt_modes(self):
        self.assertEqual(pil.analyze(self.raw(),self.trace,1,self.reset_vector)['additional_systick_after_starvation'],200)
        self.box.update(mode=2,irq_ticks=600)
        self.assertEqual(pil.analyze(self.raw(),self.trace,2,self.reset_vector)['additional_systick_after_starvation'],0)

    def test_wrong_reset_cause_or_running_core_rejected(self):
        for trace in (self.trace.replace('20000003','10000003'),self.trace.replace('Halted','Running'),
                      self.trace.replace('40012c44:  00000000','40012c44:  00008000'),
                      self.trace.replace('pc = 0x080001d8','pc = 0x080001da'),
                      self.trace.replace('xpsr = 0x01000000','xpsr = 0x01000003')):
            with self.assertRaises(ValueError): pil.analyze(self.raw(),trace,1,self.reset_vector)

    def test_stale_reset_evidence_freeze_and_disabled_tick_rejected(self):
        for key,val in (('reset_flags_cleared',0x20000000),('dbg_during',0x1000),
                        ('feeds',59),('irq_ticks',600),('tim_ccer',1),('iwdg_pr',4)):
            old=self.box[key];self.box[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError): pil.analyze(self.raw(),self.trace,1,self.reset_vector)
            self.box[key]=old


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--compiler',default='gcc')
    a=p.parse_args()
    if os.name=='nt':
        out=pil.fresh(a.output)
    else:
        # CI uses its explicit runner temp directory; this entry never opens a probe.
        out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
    fw=pil.SKILL/'firmware';exe=out/('health-test.exe' if os.name=='nt' else 'health-test')
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    build=subprocess.run([a.compiler,'-std=c99','-O2','-pipe','-Wall','-Wextra','-Werror','-I'+str(fw),
                          str(fw/'motor_td3_health.c'),str(fw/'tests/health_host.c'),'-o',str(exe)],
                         capture_output=True,text=True,env=env)
    (out/'build.log').write_text(build.stdout+build.stderr,encoding='utf-8')
    if build.returncode: raise RuntimeError('Health C build failed')
    run=subprocess.run([str(exe)],capture_output=True,text=True,env=env)
    if run.returncode: raise RuntimeError('Health C check failed: '+run.stderr)
    result=json.loads(run.stdout)
    tests=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contract))
    result.update(contract_tests=tests.testsRun,contract_tests_passed=tests.wasSuccessful())
    pil.save(out/'result.json',result);print(json.dumps(result))
    if not tests.wasSuccessful(): raise SystemExit(1)


if __name__=='__main__': main()
