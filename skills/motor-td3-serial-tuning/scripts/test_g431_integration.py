"""Test the actual locked HAL adapter with software substitutes; no hardware access."""
import argparse
import ctypes as ct
import json
import subprocess
import unittest
import copy
import struct
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import can_transport as wire
import build_g431_locked_foc as builder
import g431_locked_pil as locked_pil

SKILL=Path(__file__).resolve().parents[1]
LIB=None
BOOT=0x1234567812345678

STUB=r'''
#ifndef TD3_HOST_STUB
#define TD3_HOST_STUB
#include <stdint.h>
typedef struct { volatile uint32_t BDTR,CCER,SR; } TIM_TypeDef;
typedef struct { volatile uint32_t APB2ENR; } RCC_TypeDef;
typedef struct { volatile uint32_t IDR; } GPIO_TypeDef;
extern TIM_TypeDef test_tim;extern RCC_TypeDef test_rcc;extern GPIO_TypeDef test_gpio;
#define TIM1 (&test_tim)
#define RCC (&test_rcc)
#define GPIOB (&test_gpio)
#define RCC_APB2ENR_TIM1EN 0x800U
#define TIM_BDTR_MOE 0x8000U
#define TIM_CCER_CC1E 1U
#define TIM_CCER_CC1NE 4U
#define TIM_CCER_CC2E 16U
#define TIM_CCER_CC2NE 64U
#define TIM_CCER_CC3E 256U
#define TIM_CCER_CC3NE 1024U
#define TIM_CCER_CC4E 4096U
#define TIM_SR_BIF 128U
#define TIM_SR_B2IF 256U
#define TIM_SR_SBIF 8192U
static inline uint32_t __get_PRIMASK(void) { return 0; }
static inline void __disable_irq(void) {}
static inline void __set_PRIMASK(uint32_t p) { (void)p; }
static inline void __DMB(void) {}
static inline void __DSB(void) {}
typedef int HAL_StatusTypeDef;
typedef struct { uint32_t unused; } FDCAN_HandleTypeDef;
typedef struct { uint32_t unused; } COMP_HandleTypeDef;
typedef struct { uint32_t unused; } TIM_HandleTypeDef;
typedef struct { uint32_t IdType,FilterIndex,FilterType,FilterConfig,FilterID1,FilterID2; } FDCAN_FilterTypeDef;
typedef struct { uint32_t Identifier,IdType,RxFrameType,DataLength,FDFormat,BitRateSwitch; } FDCAN_RxHeaderTypeDef;
typedef struct { uint32_t Identifier,IdType,TxFrameType,DataLength,ErrorStateIndicator,BitRateSwitch,FDFormat,TxEventFifoControl; } FDCAN_TxHeaderTypeDef;
#define HAL_OK 0
#define FDCAN_STANDARD_ID 0
#define FDCAN_FILTER_MASK 1
#define FDCAN_FILTER_TO_RXFIFO0 1
#define FDCAN_REJECT 2
#define FDCAN_REJECT_REMOTE 1
#define FDCAN_RX_FIFO0 0
#define FDCAN_DATA_FRAME 0
#define FDCAN_CLASSIC_CAN 0
#define FDCAN_DLC_BYTES_8 8
#define FDCAN_BRS_OFF 0
#define FDCAN_ESI_ACTIVE 0
#define FDCAN_NO_TX_EVENTS 0
#define FDCAN_IT_RX_FIFO0_NEW_MESSAGE 1
#define FDCAN_IT_RX_FIFO0_MESSAGE_LOST 2
#define FDCAN_IT_BUS_OFF 4
#define FDCAN_IT_ERROR_PASSIVE 8
#define FDCAN_IT_ARB_PROTOCOL_ERROR 16
#define FDCAN_IT_DATA_PROTOCOL_ERROR 32
extern FDCAN_HandleTypeDef hfdcan1;
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *,FDCAN_FilterTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *,uint32_t,uint32_t,uint32_t,uint32_t);
HAL_StatusTypeDef HAL_FDCAN_ActivateNotification(FDCAN_HandleTypeDef *,uint32_t,uint32_t);
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *);
uint32_t HAL_FDCAN_GetRxFifoFillLevel(FDCAN_HandleTypeDef *,uint32_t);
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *,uint32_t,FDCAN_RxHeaderTypeDef *,uint8_t *);
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(FDCAN_HandleTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *,FDCAN_TxHeaderTypeDef *,uint8_t *);
/* Minimum private model interface, handwritten from the audited mapping. */
typedef struct { float Motor_OnOff;double SpeedRef; } ExtU;
typedef struct { float NNSMC_SpeedErrPrev,Integrator_DSTATE_h; } DW;
typedef struct { float spd_ki,spd_kp; } spd_kpki_type;
extern ExtU rtU;extern DW rtDW;extern spd_kpki_type spd_kpki;
#endif
'''

def deliver(obj,seq=0,expires=0):
    packet=wire.pack(obj,7,0 if obj['type']=='hello' else BOOT,seq,expires)
    for f in wire.fragment(packet,1): LIB.test_feed(f,0)
    LIB.test_poll();LIB.test_ticks(1)
    for _ in range(50): LIB.test_poll()

def hello():
    LIB.test_boot(BOOT)
    deliver({'type':'hello','profile_id':'g431-foc-locked-v1'})

class Integration(unittest.TestCase):
    def setUp(self): LIB.test_reset()
    def test_filter(self): self.assertTrue(LIB.test_filter_ok())
    def test_no_boot_identity_means_no_handshake(self):
        deliver({'type':'hello','profile_id':'g431-foc-locked-v1'})
        self.assertEqual(LIB.test_count(),0)
    def test_hello_advertises_zero_capabilities(self):
        hello();r=wire.Reassembler();packet=None
        for i in range(LIB.test_count()):
            f=ct.create_string_buffer(8)
            if LIB.test_sent(i,f)==0x621: packet=r.feed(f.raw,0) or packet
        self.assertEqual(wire.unpack(packet)[0]['capabilities'],[])
        self.assertEqual(LIB.test_guard_fault(),12)
    def test_begin_and_gains_never_enable_or_change_pi(self):
        hello();kp,ki=LIB.test_kp(),LIB.test_ki()
        deliver({'type':'begin','profile_id':'g431-foc-locked-v1','speed_ref':1000,'lease_ms':100},1,100000)
        deliver({'type':'gains','command_seq':1,'kp':.1,'ki':.1,'lease_ms':100},2,100000)
        self.assertTrue(LIB.test_off());self.assertEqual((LIB.test_kp(),LIB.test_ki()),(kp,ki))
    def test_actual_disable_preserves_adc_trigger_channel(self):
        LIB.test_software_outputs_on();LIB.motor_td3_g431_disable()
        self.assertTrue(LIB.test_off());self.assertTrue(LIB.test_ch4())
    def test_button_can_only_stop_and_latch(self):
        LIB.test_software_outputs_on();LIB.motor_td3_g431_button_stop()
        self.assertTrue(LIB.test_off());self.assertTrue(LIB.test_fault())
        LIB.motor_td3_g431_button_stop();self.assertTrue(LIB.test_off())
    def test_systick_disables_without_adc_can_or_polling(self):
        LIB.test_software_outputs_on();LIB.test_ticks(5)
        self.assertTrue(LIB.test_off());self.assertTrue(LIB.test_fault())
    def test_invalid_hall_zero_period_no_division(self):
        self.assertFalse(LIB.motor_td3_g431_hall_capture(0,5));self.assertTrue(LIB.test_fault())
    def test_invalid_hall_code(self):
        self.assertFalse(LIB.motor_td3_g431_hall_capture(100,7));self.assertTrue(LIB.test_fault())
    def test_missing_temperature_cannot_become_training_data(self):
        hello();self.assertEqual(LIB.test_telemetry(),0)
    def test_rx_overflow_latches_stop(self):
        for _ in range(65): LIB.test_feed(bytes(8),0)
        self.assertTrue(LIB.test_fault());self.assertTrue(LIB.test_off())
    def test_fd_frame_rejected(self):
        LIB.test_feed(bytes(8),1);self.assertTrue(LIB.test_fault())
    def test_bus_off_stops(self):
        LIB.test_software_outputs_on();LIB.test_can_error();self.assertTrue(LIB.test_off())
    def test_tx_failure_stops(self):
        LIB.test_boot(BOOT);LIB.test_tx_error()
        deliver({'type':'hello','profile_id':'g431-foc-locked-v1'});self.assertTrue(LIB.test_fault())
    def test_stop_keeps_inhibit(self):
        hello();deliver({'type':'stop'},1)
        self.assertTrue(LIB.test_off());self.assertEqual(LIB.test_guard_fault(),12)
    def test_break_without_callback_latches_and_stops(self):
        # Hardware flag read by the actual adapter; no COMP/TIM IRQ callback.
        for flag in (128,256,8192):
            LIB.test_reset();LIB.test_software_outputs_on();LIB.test_break_flags(flag)
            LIB.test_ticks(1)
            self.assertTrue(LIB.test_fault());self.assertTrue(LIB.test_off())
    def test_break_recovery_and_commands_do_not_clear_fault(self):
        hello();LIB.test_break_flags(128);LIB.test_ticks(1)
        LIB.test_break_flags(0);LIB.test_poll();LIB.test_ticks(1)
        deliver({'type':'stop'},1)
        deliver({'type':'begin','profile_id':'g431-foc-locked-v1','speed_ref':1000,'lease_ms':100},2,100000)
        self.assertTrue(LIB.test_fault());self.assertTrue(LIB.test_off())
    def test_clock_off_does_not_turn_stale_flags_into_fault(self):
        LIB.test_timer_clock(0);LIB.test_break_flags(128);LIB.test_ticks(1)
        self.assertFalse(LIB.test_fault())
    def test_patch_refuses_unknown_or_repeated_anchors(self):
        with self.assertRaises(ValueError): builder.replace_once('changed source','known','new')
        with self.assertRaises(ValueError): builder.replace_once('known known','known','new')

class PILContract(unittest.TestCase):
    def setUp(self):
        self.data=struct.pack('<II',0x20005000,0x20000201)+bytes(632)
        self.c=dict(schema_version=1,mode=locked_pil.MODE,entry=0x20000201,load_address=0x20000000,
            mailbox_address=0x20004400,stack_bottom=0x20004c00,stack_top=0x20005000,
            image_bytes=len(self.data),image_sha256=locked_pil.pil.sha(self.data),expected_cases=11,
            external_can=False,motor_output=False,flash_programming=False,full_foc_executed=False,
            source_sha256={s:locked_pil.pil.sha((SKILL/'firmware'/s).read_bytes()) for s in locked_pil.SOURCES})
    def test_contract_fixture_valid(self): locked_pil.validate(self.c,self.data)
    def test_power_ack_rejected_before_probe_or_file_access(self):
        with patch.object(locked_pil.pil,'session',side_effect=AssertionError('Probe opened')):
            with self.assertRaises(ValueError): locked_pil.run(SimpleNamespace(power_stage_disconnected=False,reset_and_halt_ack=True))
            with self.assertRaises(ValueError): locked_pil.run(SimpleNamespace(power_stage_disconnected=True,reset_and_halt_ack=False))
    def test_motion_flash_or_full_foc_contract_rejected(self):
        for field in ('motor_output','flash_programming','full_foc_executed','external_can'):
            c=copy.deepcopy(self.c);c[field]=True
            with self.assertRaises(ValueError): locked_pil.validate(c,self.data)
    def test_changed_image_or_entry_rejected(self):
        with self.assertRaises(ValueError): locked_pil.validate(self.c,self.data[:-1]+b'x')
        c=copy.deepcopy(self.c);c['entry']=0x08000101
        with self.assertRaises(ValueError): locked_pil.validate(c,self.data)
    def test_changed_or_incomplete_source_contract_rejected(self):
        c=copy.deepcopy(self.c);c['source_sha256'].pop('motor_td3_g431_off.h')
        with self.assertRaises(ValueError): locked_pil.validate(c,self.data)
        c=copy.deepcopy(self.c);c['source_sha256']['motor_td3_g431_off.h']='0'*64
        with self.assertRaises(ValueError): locked_pil.validate(c,self.data)

def main():
    global LIB
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--compiler',default='gcc')
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()): raise ValueError('Use a fresh task directory')
    for name in ('stm32g431xx.h','main.h','fdcan.h','FOC_Model.h'): (out/name).write_text(STUB,encoding='ascii')
    lib=out/'adapter.dll' if __import__('os').name=='nt' else out/'adapter.so'
    fw=SKILL/'firmware'
    result=subprocess.run([a.compiler,'-shared','-fPIC','-std=c99','-O2','-Wall','-Wextra','-Werror',
        '-I',str(out),'-I',str(fw),str(fw/'tests/g431_adapter_host.c'),str(fw/'motor_td3_can.c'),
        str(fw/'motor_td3_can_control.c'),str(fw/'motor_td3_guard.c'),'-lm','-o',str(lib)],capture_output=True,text=True)
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode: raise RuntimeError('Host adapter compilation failed; inspect build.log')
    LIB=ct.CDLL(str(lib));LIB.test_boot.argtypes=[ct.c_uint64]
    LIB.test_kp.restype=LIB.test_ki.restype=ct.c_float
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(t) for t in (Integration,PILContract)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'schema_version':1,'scope':'actual locked adapter with software HAL/CMSIS/model substitutes',
        'tests':r.testsRun,'adapter_tests':19,'pil_contract_tests':5,'failures':len(r.failures),'errors':len(r.errors),'passed':r.wasSuccessful(),
        'hardware_accessed':False,'motor_output':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if not r.wasSuccessful(): raise SystemExit(1)

if __name__=='__main__': main()
