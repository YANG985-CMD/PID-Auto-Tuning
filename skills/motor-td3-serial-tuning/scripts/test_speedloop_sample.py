"""Check real diagnostic sampler with software ADC failures. No hardware access."""
import argparse
import ctypes as ct
import json
import math
import os
import subprocess
import unittest
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]
LIB=None
STUB='''#ifndef SAMPLE_STUB
#define SAMPLE_STUB
#include <stdint.h>
typedef struct { unsigned unused; } ADC_HandleTypeDef;
typedef struct { float ia,ib,ic,v_bus; } ExtU;
extern ADC_HandleTypeDef hadc1,hadc2;extern ExtU rtU;
#define HAL_OK 0
#define ADC_INJECTED_RANK_1 1
#define ADC_INJECTED_RANK_2 2
int HAL_ADCEx_InjectedStart(ADC_HandleTypeDef *);
int HAL_ADCEx_InjectedPollForConversion(ADC_HandleTypeDef *,uint32_t);
uint32_t HAL_ADCEx_InjectedGetValue(ADC_HandleTypeDef *,uint32_t);
int HAL_ADC_Start(ADC_HandleTypeDef *);
int HAL_ADC_PollForConversion(ADC_HandleTypeDef *,uint32_t);
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef *);
#endif
'''


class Sampling(unittest.TestCase):
    def setUp(self): LIB.test_reset()
    def calibrate(self):
        for _ in range(10): LIB.test_sample(0)
    def test_ten_complete_samples_calibrate_in_original_phase_order(self):
        for _ in range(9): LIB.test_sample(0)
        self.assertFalse(LIB.test_calibrated())
        LIB.test_sample(0)
        self.assertTrue(LIB.test_calibrated())
        self.assertEqual([LIB.test_offset(i) for i in range(3)],[2021,2029,2025])
        self.assertEqual(LIB.test_count(),10)
    def test_nominal_positive_and_negative_codes_preserve_sign(self):
        self.calibrate();LIB.test_raw(2020,2031,2022,1150);LIB.test_sample(0)
        for i,codes in enumerate((-1,2,-3)):
            self.assertAlmostEqual(LIB.test_current(i),codes*.02197265625)
    def test_incomplete_offset_does_not_invent_zero_current(self):
        LIB.test_sample(0)
        self.assertFalse(LIB.test_calibrated())
        self.assertTrue(all(math.isnan(LIB.test_current(i)) for i in range(3)))
    def test_bus_is_from_completed_regular_conversion(self):
        LIB.test_sample(0);self.assertAlmostEqual(LIB.test_bus(),1150*3.3/4096*26,places=5)
    def test_each_start_or_timeout_invalidates_and_cannot_refresh_sample(self):
        for fail in range(1,9):
            with self.subTest(fail=fail):
                LIB.test_reset();LIB.test_sample(fail)
                self.assertEqual((LIB.test_count(),LIB.test_fresh()),(0,0))
                self.assertEqual((LIB.test_errors(),LIB.test_faults()),(1,1))
                self.assertTrue(math.isnan(LIB.test_bus()))
                self.assertTrue(all(math.isnan(LIB.test_current(i)) for i in range(3)))
                self.assertGreaterEqual(LIB.test_disabled(),2)
    def test_zero_and_fullscale_do_not_overflow_offset_accumulation(self):
        LIB.test_raw(0,4095,4095,4095);self.calibrate()
        self.assertEqual([LIB.test_offset(i) for i in range(3)],[0,4095,4095])
    def test_out_of_range_data_is_not_accepted(self):
        for raw in ((4096,2029,2025,1150),(2021,4096,2025,1150),
                    (2021,2029,4096,1150),(2021,2029,2025,4096)):
            LIB.test_reset();LIB.test_raw(*raw);LIB.test_sample(0)
            self.assertEqual((LIB.test_count(),LIB.test_fresh()),(0,0))
            self.assertTrue(LIB.test_faults())


def main():
    global LIB
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--compiler',default='gcc')
    a=p.parse_args();out=Path(a.output).resolve()
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh task directory')
    out.mkdir(parents=True,exist_ok=True)
    for name in ('adc.h','FOC_Model.h'): (out/name).write_text(STUB,encoding='ascii')
    lib=out/('sample.dll' if os.name=='nt' else 'sample.so');fw=SKILL/'firmware'
    environment=os.environ.copy();environment.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    r=subprocess.run([a.compiler,'-shared','-fPIC','-std=c99','-O2','-pipe','-Wall','-Wextra','-Werror',
        '-I',str(out),'-I',str(fw),str(fw/'tests/speedloop_sample_host.c'),'-lm','-o',str(lib)],env=environment,capture_output=True,text=True)
    (out/'build.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode: raise RuntimeError('Sampler host compilation failed; inspect build.log')
    LIB=ct.CDLL(str(lib));LIB.test_current.restype=LIB.test_bus.restype=ct.c_float
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Sampling))
    summary=dict(schema_version=1,scope='diagnostic sampler with software ADC substitutes',
        tests=result.testsRun,passed=result.wasSuccessful(),hardware_accessed=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if not result.wasSuccessful(): raise SystemExit(1)


if __name__=='__main__': main()
