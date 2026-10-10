"""Test the actual locked HAL adapter with software substitutes; no hardware access."""
import argparse
import ctypes as ct
import json
import os
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
PROFILE='g431-foc-locked-v1'

STUB=r'''
#ifndef TD3_HOST_STUB
#define TD3_HOST_STUB
#include <stdint.h>
typedef struct { volatile uint32_t BDTR,CCER,SR,CR1; } TIM_TypeDef;
typedef struct { volatile uint32_t APB2ENR,CSR; } RCC_TypeDef;
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
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
typedef struct { volatile uint32_t KR,PR,RLR,SR,WINR; } IWDG_TypeDef;
typedef struct { volatile uint32_t OPTR; } FLASH_TypeDef;
typedef struct { volatile uint32_t APB1FZR1; } DBGMCU_TypeDef;
extern IWDG_TypeDef test_iwdg;extern FLASH_TypeDef test_flash;extern DBGMCU_TypeDef test_debug;
#define IWDG (&test_iwdg)
#define FLASH (&test_flash)
#define DBGMCU (&test_debug)
#define FLASH_OPTR_IWDG_SW 0x10000U
#define DBGMCU_APB1FZR1_DBG_IWDG_STOP 0x1000U
#define RCC_CSR_RMVF 0x800000U
#define RCC_CSR_IWDGRSTF 0x20000000U
#define TIM_CR1_CEN 1U
static inline void __NOP(void) {}
#endif
static inline uint32_t __get_PRIMASK(void) { return 0; }
static inline void __disable_irq(void) {}
extern void test_unlock_hook(void);
static inline void __set_PRIMASK(uint32_t p) { (void)p;test_unlock_hook(); }
static inline void __DMB(void) {}
static inline void __DSB(void) {}
typedef int HAL_StatusTypeDef;
typedef struct { volatile uint32_t TXEFS; } FDCAN_TypeDef;
typedef struct { FDCAN_TypeDef *Instance; } FDCAN_HandleTypeDef;
typedef struct { uint32_t unused; } COMP_HandleTypeDef;
typedef struct { uint32_t unused; } TIM_HandleTypeDef;
typedef struct { uint32_t IdType,FilterIndex,FilterType,FilterConfig,FilterID1,FilterID2; } FDCAN_FilterTypeDef;
typedef struct { uint32_t Identifier,IdType,RxFrameType,DataLength,FDFormat,BitRateSwitch; } FDCAN_RxHeaderTypeDef;
typedef struct { uint32_t Identifier,IdType,TxFrameType,DataLength,ErrorStateIndicator,BitRateSwitch,FDFormat,TxEventFifoControl,MessageMarker; } FDCAN_TxHeaderTypeDef;
typedef struct { uint32_t Identifier,IdType,TxFrameType,DataLength,BitRateSwitch,FDFormat,MessageMarker,EventType; } FDCAN_TxEventFifoTypeDef;
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
#define FDCAN_STORE_TX_EVENTS 0x800000U
#define FDCAN_TX_EVENT 0x400000U
#define FDCAN_TXEFS_EFFL 7U
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
HAL_StatusTypeDef HAL_FDCAN_GetTxEvent(FDCAN_HandleTypeDef *,FDCAN_TxEventFifoTypeDef *);
/* Minimum private model interface, handwritten from the audited mapping. */
typedef struct { float Motor_OnOff;double SpeedRef; } ExtU;
#ifdef MOTOR_TD3_SPEEDLOOP_DIAGNOSTIC
typedef struct { float Integrator_DSTATE_h; } DW;
#else
typedef struct { float NNSMC_SpeedErrPrev,Integrator_DSTATE_h; } DW;
#endif
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
    deliver({'type':'hello','profile_id':PROFILE})

class Integration(unittest.TestCase):
    def setUp(self): LIB.test_reset()
    def test_filter(self): self.assertTrue(LIB.test_filter_ok())
    def test_no_boot_identity_means_no_handshake(self):
        deliver({'type':'hello','profile_id':PROFILE})
        self.assertEqual(LIB.test_count(),0)
    def test_hello_advertises_zero_capabilities(self):
        hello();r=wire.Reassembler();packet=None
        for i in range(LIB.test_count()):
            f=ct.create_string_buffer(8)
            if LIB.test_sent(i,f)==0x621: packet=r.feed(f.raw,0) or packet
        self.assertEqual(wire.unpack(packet)[0]['capabilities'],[])
        self.assertEqual(LIB.test_guard_fault(),12)
    def test_systick_hello_acceptance_cannot_send_raw_before_reply(self):
        LIB.test_boot(BOOT)
        request=wire.pack({'type':'hello','profile_id':PROFILE},7)
        for f in wire.fragment(request,1): LIB.test_feed(f,0)
        LIB.test_poll()  # Queued, but not yet accepted by SysTick.
        # clock read, main_seen update, then HELLO check unlock: interrupt there.
        LIB.test_arm_unlock_tick(3);LIB.test_poll()
        for _ in range(50): LIB.test_poll()
        r=wire.Reassembler();packet=None;saw_raw=False
        for i in range(LIB.test_count()):
            f=ct.create_string_buffer(8);identifier=LIB.test_sent(i,f)
            if identifier==0x621:
                self.assertFalse(saw_raw);packet=r.feed(f.raw,0) or packet
            else:
                self.assertIsNotNone(packet);saw_raw=True
        self.assertIsNotNone(packet);self.assertTrue(saw_raw)
    def test_diagnostic_hall_order_matches_legacy_pb8_pb7_pb6(self):
        # Original capture mapping: PB8 is bit0, PB7 bit1, PB6 bit2.
        for code,pins in ((1,0x100),(2,0x80),(3,0x180),(4,0x40),(5,0x140),(6,0xc0)):
            LIB.test_reset();LIB.test_hall_pins(pins);hello()
            status=None
            for i in range(LIB.test_count()):
                f=ct.create_string_buffer(8)
                if LIB.test_sent(i,f)==0x622: status=f.raw
            self.assertIsNotNone(status)
            self.assertEqual(status[4],code)
    def test_begin_and_gains_never_enable_or_change_pi(self):
        hello();kp,ki=LIB.test_kp(),LIB.test_ki()
        deliver({'type':'begin','profile_id':PROFILE,'speed_ref':1000,'lease_ms':100},1,100000)
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
        deliver({'type':'hello','profile_id':PROFILE});self.assertTrue(LIB.test_fault())
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
        deliver({'type':'begin','profile_id':PROFILE,'speed_ref':1000,'lease_ms':100},2,100000)
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

class WatchdogIntegration(unittest.TestCase):
    def setUp(self): LIB.test_reset()
    def advance(self,count,adc=True):
        for _ in range(count):
            LIB.test_ticks(1)
            if adc: LIB.test_adc()
            LIB.test_poll()
    def test_healthy_foreground_adc_and_tick_feed(self):
        self.advance(100)
        self.assertEqual(LIB.test_wd_fault(),0);self.assertGreater(LIB.test_wd_feeds(),90)
        self.assertEqual(LIB.test_wd_freeze(),0);self.assertTrue(LIB.test_off())
    def test_watchdog_register_sync_precedes_health_deadlines(self):
        LIB.test_wd_delayed_init(6);self.advance(10)
        self.assertEqual(LIB.test_fault(),0);self.assertEqual(LIB.test_wd_fault(),0)
        self.assertGreater(LIB.test_wd_feeds(),0)
    def test_systick_alone_never_feeds(self):
        self.advance(1);feeds=LIB.test_wd_feeds();LIB.test_ticks(4)
        self.assertEqual(LIB.test_wd_feeds(),feeds)
    def test_stale_foreground_fault_before_refresh(self):
        self.advance(1);LIB.test_ticks(5);LIB.test_poll()
        self.assertEqual(LIB.test_wd_fault(),4);self.assertTrue(LIB.test_off())
    def test_adc_stale_and_late_sample_cannot_recover(self):
        self.advance(1);self.advance(30,False)
        self.assertEqual(LIB.test_wd_fault(),6);feeds=LIB.test_wd_feeds()
        self.advance(10);self.assertEqual(LIB.test_wd_feeds(),feeds)
        self.assertEqual(LIB.test_wd_fault(),6)
    def test_validated_stop_heartbeats_keep_session_healthy(self):
        hello()
        for seq in range(1,6):
            deliver({'type':'stop'},seq);self.advance(50)
        self.assertEqual(LIB.test_wd_fault(),0);self.assertEqual(LIB.test_wd_seq(),5)
        self.assertTrue(LIB.test_off())
    def test_late_heartbeat_cannot_revive_expired_link(self):
        hello();deliver({'type':'stop'},1);self.advance(201)
        self.assertEqual(LIB.test_wd_fault(),7);feeds=LIB.test_wd_feeds()
        deliver({'type':'stop'},2);self.advance(2)
        self.assertEqual(LIB.test_wd_fault(),7);self.assertEqual(LIB.test_wd_feeds(),feeds)
    def test_duplicate_sequence_causes_latched_protocol_fault(self):
        hello();deliver({'type':'stop'},1);deliver({'type':'stop'},1);LIB.test_poll()
        self.assertEqual(LIB.test_wd_fault(),8);self.assertTrue(LIB.test_off())
    def test_wrong_boot_cannot_refresh_heartbeat(self):
        hello();packet=wire.pack({'type':'stop'},7,BOOT+1,1)
        for f in wire.fragment(packet,2): LIB.test_feed(f,0)
        LIB.test_poll();LIB.test_ticks(1);LIB.test_poll()
        self.assertEqual(LIB.test_wd_seq(),0);self.assertEqual(LIB.test_wd_fault(),8)
    def test_corrupt_crc_cannot_refresh_heartbeat(self):
        hello();frames=wire.fragment(wire.pack({'type':'stop'},7,BOOT,1),2)
        last=bytearray(frames[-1]);last[-1]^=1;frames[-1]=bytes(last)
        for f in frames: LIB.test_feed(f,0)
        LIB.test_poll();LIB.test_ticks(1);LIB.test_poll()
        self.assertEqual(LIB.test_wd_seq(),0);self.assertEqual(LIB.test_wd_fault(),8)
    def test_reset_cause_latches_before_peripheral_init(self):
        self.assertEqual(LIB.test_wd_boot(0x20000000),1)
        self.assertEqual(LIB.test_wd_boot_latched(),1)
        self.assertEqual(LIB.motor_td3_g431_wd_init(0),0)
        self.assertEqual(LIB.test_wd_active(),0);self.assertTrue(LIB.test_off())
    def test_running_initialization_cannot_clear_fault(self):
        self.advance(1);self.advance(30,False)
        self.assertEqual(LIB.motor_td3_g431_wd_init(0),0)
        self.assertEqual(LIB.test_wd_fault(),6)
    def test_tx_waits_for_actual_event_without_blocking_health(self):
        LIB.test_tx_hold(1);hello();self.assertEqual(LIB.test_count(),1)
        self.advance(20);self.assertEqual(LIB.test_count(),1)
        self.assertEqual(LIB.test_wd_fault(),0);self.assertGreater(LIB.test_wd_feeds(),10)
        LIB.test_tx_hold(0)
        for _ in range(50): LIB.test_poll()
        r=wire.Reassembler();packet=None;raw=[]
        for i in range(LIB.test_count()):
            f=ct.create_string_buffer(8);identifier=LIB.test_sent(i,f)
            if identifier==0x621: packet=r.feed(f.raw,0) or packet
            else: raw.append(identifier)
        self.assertEqual(wire.unpack(packet)[0]['capabilities'],[])
        self.assertEqual(raw,[0x622,0x623,0x624,0x625])
    def test_missing_tx_event_latches_timeout_and_stops_feeding(self):
        LIB.test_tx_hold(1);hello();self.advance(51)
        self.assertEqual(LIB.test_count(),1);self.assertTrue(LIB.test_fault())
        self.assertEqual(LIB.test_wd_fault(),8);feeds=LIB.test_wd_feeds()
        self.advance(5);self.assertEqual(LIB.test_wd_feeds(),feeds);self.assertTrue(LIB.test_off())
    def test_wrong_tx_event_marker_is_rejected(self):
        LIB.test_tx_hold(1);hello();LIB.test_tx_bad_marker();LIB.test_tx_hold(0);LIB.test_poll();LIB.test_poll()
        self.assertTrue(LIB.test_fault());self.assertEqual(LIB.test_count(),1)
        self.assertEqual(LIB.test_wd_fault(),8)

def main():
    global LIB,PROFILE
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--compiler',default='gcc')
    p.add_argument('--speedloop',action='store_true',help='Compile against SpeedLoop state fields and diagnostic identity')
    p.add_argument('--watchdog',action='store_true',help='Test real diagnostic watchdog glue with software registers')
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if a.speedloop: PROFILE='g431-speedloop-diag-v1'
    if a.watchdog: a.speedloop=True;PROFILE='g431-speedloop-wdog-v1'
    if any(out.iterdir()): raise ValueError('Use a fresh task directory')
    for name in ('stm32g431xx.h','main.h','fdcan.h','FOC_Model.h'): (out/name).write_text(STUB,encoding='ascii')
    lib=out/'adapter.dll' if __import__('os').name=='nt' else out/'adapter.so'
    fw=SKILL/'firmware'
    variant=['-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC'] if a.speedloop else []
    extra=[]
    if a.watchdog:
        variant+=['-DMOTOR_TD3_SPEEDLOOP_WATCHDOG']
        extra=[str(fw/'motor_td3_health.c'),str(fw/'motor_td3_g431_watchdog.c')]
    environment=os.environ.copy();environment.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    result=subprocess.run([a.compiler,'-shared','-fPIC','-std=c99','-O2','-pipe','-Wall','-Wextra','-Werror',*variant,
        '-I',str(out),'-I',str(fw),str(fw/'tests/g431_adapter_host.c'),str(fw/'motor_td3_can.c'),
        str(fw/'motor_td3_can_control.c'),str(fw/'motor_td3_guard.c'),*extra,'-lm','-o',str(lib)],env=environment,capture_output=True,text=True)
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode: raise RuntimeError('Host adapter compilation failed; inspect build.log')
    LIB=ct.CDLL(str(lib));LIB.test_boot.argtypes=[ct.c_uint64]
    LIB.test_kp.restype=LIB.test_ki.restype=ct.c_float
    classes=(WatchdogIntegration,) if a.watchdog else (Integration,PILContract)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(t) for t in classes])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'schema_version':1,'scope':'actual locked adapter with software HAL/CMSIS/model substitutes',
        'tests':r.testsRun,'watchdog_integration':a.watchdog,
        'failures':len(r.failures),'errors':len(r.errors),'passed':r.wasSuccessful(),
        'hardware_accessed':False,'motor_output':False,'profile':PROFILE}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if not r.wasSuccessful(): raise SystemExit(1)

if __name__=='__main__': main()
