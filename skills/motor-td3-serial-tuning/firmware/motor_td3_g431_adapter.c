/* Integration adapter for audited G431 examples.
 * The default build is motion-inhibited. MOTOR_TD3_SPEEDLOOP_PI_MOTION adds
 * an explicitly bounded CAN BEGIN/GAINS path; the hardware COMP/TIM1 Break,
 * Hall validation, ADC freshness, lease and link watchdog remain independent
 * stop paths. Raw diagnostic IDs 622..625 are never TD3 training telemetry. */
#include "motor_td3_g431_adapter.h"
#include "motor_td3_g431_off.h"
#include "motor_td3_can_control.h"
#include "motor_td3_speedloop_can.h"
#include "main.h"
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
#include "tim.h"
#endif
#include "fdcan.h"
#include "FOC_Model.h"
#include <math.h>
#include <string.h>
#if defined(MOTOR_TD3_SPEEDLOOP_PI_MOTION)
#define LOCKED_FIRMWARE "g431-speedloop-pi-motion-v3"
#define LOCKED_PROFILE "g431-speedloop-pi-motion-v3"
#elif defined(MOTOR_TD3_SPEEDLOOP_WATCHDOG)
#include "motor_td3_g431_watchdog.h"
#endif

#define RX_CAPACITY 64U
#define MAIN_DEADLINE_US 5000U
#define TX_DEADLINE_US 50000U
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
#define DIAG_PERIOD_US 20000U
#else
#define DIAG_PERIOD_US 100000U
#endif
#if !defined(MOTOR_TD3_SPEEDLOOP_PI_MOTION) && defined(MOTOR_TD3_SPEEDLOOP_WATCHDOG)
#define LOCKED_FIRMWARE "g431-speedloop-wdog-v1"
#define LOCKED_PROFILE "g431-speedloop-wdog-v1"
#elif !defined(MOTOR_TD3_SPEEDLOOP_PI_MOTION) && defined(MOTOR_TD3_SPEEDLOOP_DIAGNOSTIC)
#define LOCKED_FIRMWARE "g431-speedloop-diag-v1"
#define LOCKED_PROFILE "g431-speedloop-diag-v1"
#elif !defined(MOTOR_TD3_SPEEDLOOP_PI_MOTION)
#define LOCKED_FIRMWARE "g431-foc-can-locked-v1"
#define LOCKED_PROFILE "g431-foc-locked-v1"
#endif
extern uint8_t Motor_state,ADC_offset;
extern float Ia,Ib,Ic,Vbus,HallSpeed,HallThetaAdd;
volatile uint64_t motor_td3_g431_debugger_boot_token;
static motor_td3_can_control endpoint;
static volatile uint64_t now_us;
static volatile uint32_t ring_write,ring_read,irq_fault,initialized;
static uint64_t main_seen_us,adc_seen_us,tx_started_us,diag_due_us;
static volatile uint32_t adc_samples,hall_bad;
static uint8_t ring[RX_CAPACITY][8],tx_packet[TD3_CAN_MAX_PACKET];
static uint64_t ring_time[RX_CAPACITY];
static uint32_t tx_length,tx_index,diag_index;
static uint8_t tx_transfer;
static int endpoint_ready;
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
static volatile uint8_t motion_enabled;
static uint64_t bus_seen_us;
/* The first board trial uses only the already observed 1000 rpm baseline. */
static const float live_refs[] = {1000.0f};
static const motor_td3_limits live_limits = {
    .kp_min=0.0013556f,.kp_max=0.0054224f,.ki_min=0.00072f,.ki_max=0.00216f,
    .kp_step=0.00027112f,.ki_step=0.000144f,.kp_baseline=0.003389f,.ki_baseline=0.00144f,
    .current_limit=2.0f,.speed_limit=1800.0f,.vbus_min=18.0f,.vbus_max=30.0f,
    .temperature_limit=-1.0f, /* no sensor on this board; thermal guard disabled */
    .lease_max_us=250000U,.link_timeout_us=100000U,.trial_max_us=3000000U,.command_max=60U
};
static void phase_pins_low(void) {
    GPIOA->BSRR=(GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10)<<16;
    GPIOB->BSRR=(GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15)<<16;
    GPIOA->MODER=(GPIOA->MODER&~((3U<<16)|(3U<<18)|(3U<<20)))|
        (1U<<16)|(1U<<18)|(1U<<20);
    GPIOB->MODER=(GPIOB->MODER&~((3U<<26)|(3U<<28)|(3U<<30)))|
        (1U<<26)|(1U<<28)|(1U<<30);
    __DSB();
}
#endif
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
static uint32_t tx_inflight,tx_frame_id;
static uint8_t tx_marker;
static uint64_t tx_queued_us;
volatile uint32_t motor_td3_g431_tx_fault;
volatile FDCAN_TxEventFifoTypeDef motor_td3_g431_tx_last_event;
#endif

static uint32_t lock(void) { uint32_t p=__get_PRIMASK(); __disable_irq(); return p; }
static void unlock(uint32_t p) { __set_PRIMASK(p); }
static uint64_t clock_us(void) { uint32_t p=lock(); uint64_t n=now_us; unlock(p); return n; }
void motor_td3_g431_disable(void) {
    motor_td3_g431_outputs_off(); Motor_state=0; rtU.Motor_OnOff=0.0F;
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
    motion_enabled=0;
    phase_pins_low();
#endif
}
static void disable_hook(void *u) { (void)u; motor_td3_g431_disable(); }
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
static uint8_t hall_code(void) {
    return (uint8_t)(((GPIOB->IDR>>8)&1U)|((GPIOB->IDR>>6)&2U)|((GPIOB->IDR>>4)&4U));
}
static int motion_begin(void *u,float ref,float kp,float ki) {
    (void)u;(void)kp;(void)ki;
    if(irq_fault||motor_td3_g431_break_seen()||!ADC_offset||Vbus<18.0f||Vbus>30.0f||
       hall_code()==0U||hall_code()>=7U||adc_samples<100U||
       clock_us()-adc_seen_us>=5000U||!bus_seen_us||clock_us()-bus_seen_us>=30000U||
       !(TIM1->BDTR&TIM_BDTR_MOE)) {
        motor_td3_g431_disable(); return 0;
    }
    /* Called with interrupts serialized at the generated PI boundary.
     * All phases remain disconnected while pin ownership and CCRs change. */
    TIM1->CCER&=~TD3_G431_PHASE_MASK;
    TIM1->CCR1=4000U;TIM1->CCR2=4000U;TIM1->CCR3=4000U;
    TIM1->EGR=TIM_EGR_UG;
    GPIOA->MODER=(GPIOA->MODER&~((3U<<16)|(3U<<18)|(3U<<20)))|
        (2U<<16)|(2U<<18)|(2U<<20);
    GPIOB->MODER=(GPIOB->MODER&~((3U<<26)|(3U<<28)|(3U<<30)))|
        (2U<<26)|(2U<<28)|(2U<<30);
    rtU.SpeedRef=ref;
    Motor_state=1;rtU.Motor_OnOff=1.0F;
    TIM1->CCER|=TD3_G431_PHASE_MASK;__DSB();motion_enabled=1;
    return motor_td3_g431_outputs_enabled()!=0;
}
static int motion_apply(void *u,float kp,float ki) {
    (void)u;(void)kp;(void)ki;
    return motion_enabled && motor_td3_g431_outputs_enabled() && !motor_td3_g431_break_seen();
}
#endif
int motor_td3_g431_sampling_ready(void) {
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
    if(!endpoint_ready||irq_fault||motor_td3_g431_break_seen()) {
        motor_td3_g431_disable(); return 0;
    }
    /* HAL starts CH4 only. MOE must stay high for its ADC trigger, while the
     * phase CCER bits are zero and all six gate pins are GPIO low. */
    TIM1->CCER&=~TD3_G431_PHASE_MASK;
    phase_pins_low();return 1;
#else
    return 0;
#endif
}
#ifndef MOTOR_TD3_SPEEDLOOP_PI_MOTION
static int reject_begin(void *u,float ref,float kp,float ki) {
    (void)u;(void)ref;(void)kp;(void)ki;motor_td3_g431_disable();return 0;
}
static int reject_apply(void *u,float kp,float ki) {
    (void)u;(void)kp;(void)ki;motor_td3_g431_disable();return 0;
}
#endif
static int actual_snapshot(void *u,motor_td3_telemetry *t) {
    uint32_t p=lock(); (void)u;
    memset(t,0,sizeof(*t));
    t->enabled=motor_td3_g431_outputs_enabled()!=0;
    t->kp=spd_kpki.spd_kp; t->ki=spd_kpki.spd_ki;
    t->speed_ref=(float)rtU.SpeedRef; t->speed=HallSpeed;
    /* Existing PREV_U already contains Ki*error (or anti-windup zero).
     * These are raw observations, not normalized training state. */
#ifdef MOTOR_TD3_SPEEDLOOP_DIAGNOSTIC
    t->error_history=NAN; /* SpeedLoop has no equivalent previous-error field. */
#else
    t->error_history=rtDW.NNSMC_SpeedErrPrev;
#endif
    t->integral_output=rtDW.Integrator_DSTATE_h;
    t->current=fmaxf(fabsf(Ia),fmaxf(fabsf(Ib),fabsf(Ic)));
    t->vbus=Vbus;
    t->temperature_c=NAN; /* No measured thermal signal in this example. */
    unlock(p); return 1;
}
void motor_td3_g431_init(void) {
    FDCAN_FilterTypeDef f;
    memset(&f,0,sizeof(f));
    motor_td3_g431_disable();
    f.IdType=FDCAN_STANDARD_ID; f.FilterIndex=0; f.FilterType=FDCAN_FILTER_MASK;
    f.FilterConfig=FDCAN_FILTER_TO_RXFIFO0; f.FilterID1=TD3_CAN_REQUEST_ID;f.FilterID2=0x7FFU;
    if(HAL_FDCAN_ConfigFilter(&hfdcan1,&f)!=HAL_OK ||
       HAL_FDCAN_ConfigGlobalFilter(&hfdcan1,FDCAN_REJECT,FDCAN_REJECT,FDCAN_REJECT_REMOTE,FDCAN_REJECT_REMOTE)!=HAL_OK ||
       HAL_FDCAN_ActivateNotification(&hfdcan1,FDCAN_IT_RX_FIFO0_NEW_MESSAGE|FDCAN_IT_RX_FIFO0_MESSAGE_LOST|
           FDCAN_IT_BUS_OFF|FDCAN_IT_ERROR_PASSIVE|FDCAN_IT_ARB_PROTOCOL_ERROR|FDCAN_IT_DATA_PROTOCOL_ERROR,0)!=HAL_OK ||
       HAL_FDCAN_Start(&hfdcan1)!=HAL_OK) irq_fault=1;
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
    {
        const motor_td3_can_hooks board={0,disable_hook,motion_begin,motion_apply,actual_snapshot};
        motor_td3_can_hooks hooks;
        uint64_t boot=motor_td3_g431_debugger_boot_token;
        motor_td3_g431_debugger_boot_token=0; /* Host writes a unique token at main() while power is off. */
        if(!boot||!motor_td3_speedloop_can_attach(&pi_link,&endpoint,&board,&hooks) ||
           !motor_td3_can_control_init(&endpoint,&live_limits,&hooks,
               boot,LOCKED_FIRMWARE,LOCKED_PROFILE,live_refs,
               sizeof(live_refs)/sizeof(live_refs[0]),100000U,TD3_CAN_CAPABILITIES_ALL))
            irq_fault=1;
        else endpoint_ready=1;
    }
#endif
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
    if(!motor_td3_g431_wd_init(clock_us())) motor_td3_g431_fault_irq();
#endif
    main_seen_us=clock_us(); initialized=1;
}
void motor_td3_g431_tick_1ms(void) {
    /* ADC has higher priority than SysTick. Serialize timestamp capture AND
     * guard publication, otherwise ADC can publish a newer tick in between. */
    uint32_t p=lock();
    now_us+=1000U;
    if(motor_td3_g431_break_seen()) motor_td3_g431_fault_irq();
    if(initialized && now_us-main_seen_us>=MAIN_DEADLINE_US) irq_fault=1;
    /* A stalled foreground must disable hardware even before any endpoint
     * owner exists; publishing a flag alone is not a stop action. */
    if(irq_fault) motor_td3_g431_disable();
    if(endpoint_ready) {
        if(irq_fault) endpoint.rx_fault=1;
        {
            int estop=irq_fault||motor_td3_g431_break_seen()||!ADC_offset||
                (now_us>adc_seen_us && now_us-adc_seen_us>5000U);
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
            /* BEGIN/GAINS are only legal at the generated 1 ms PI boundary;
             * HELLO/STOP and expired commands remain serviced here. */
            estop=estop||!bus_seen_us||now_us-bus_seen_us>=30000U;
            motor_td3_can_control_tick_ready(&endpoint,now_us,estop,0);
#else
            motor_td3_can_control_tick(&endpoint,now_us,estop);
#endif
        }
    }
    unlock(p);
}
void motor_td3_g431_adc_sample(void) {
    uint32_t p=lock(); adc_seen_us=clock_us(); ++adc_samples; unlock(p);
}
void motor_td3_g431_bus_sample(void) {
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
    uint32_t p=lock();bus_seen_us=clock_us();unlock(p);
#endif
}
int motor_td3_g431_hall_capture(uint32_t ticks,uint8_t code) {
    if(!ticks||code==0||code>6) {
        hall_bad=1; HallSpeed=0.0F;HallThetaAdd=0.0F;
        motor_td3_g431_fault_irq();return 0;
    }
    return 1;
}
void motor_td3_g431_button_stop(void) { motor_td3_g431_fault_irq(); }
void motor_td3_g431_fault_irq(void) { irq_fault=1;motor_td3_g431_disable(); }

void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *h,uint32_t flags) {
    unsigned count=0; FDCAN_RxHeaderTypeDef header; uint8_t bytes[64];
    if(h!=&hfdcan1) return;
    if(flags & FDCAN_IT_RX_FIFO0_MESSAGE_LOST) motor_td3_g431_fault_irq();
    /* G4 hardware RX FIFO contains only three entries; bounded drain. */
    while(count++<3 && HAL_FDCAN_GetRxFifoFillLevel(h,FDCAN_RX_FIFO0)) {
        if(HAL_FDCAN_GetRxMessage(h,FDCAN_RX_FIFO0,&header,bytes)!=HAL_OK) { motor_td3_g431_fault_irq();break; }
        if(header.Identifier!=TD3_CAN_REQUEST_ID || header.IdType!=FDCAN_STANDARD_ID ||
           header.RxFrameType!=FDCAN_DATA_FRAME || header.FDFormat!=FDCAN_CLASSIC_CAN ||
           header.DataLength!=FDCAN_DLC_BYTES_8 || header.BitRateSwitch!=FDCAN_BRS_OFF ||
           ring_write-ring_read>=RX_CAPACITY) { motor_td3_g431_fault_irq();continue; }
        memcpy(ring[ring_write%RX_CAPACITY],bytes,8);
        ring_time[ring_write%RX_CAPACITY]=now_us; __DMB(); ++ring_write;
    }
}
void HAL_FDCAN_ErrorCallback(FDCAN_HandleTypeDef *h) { if(h==&hfdcan1) motor_td3_g431_fault_irq(); }
void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *h,uint32_t flags) { (void)flags;if(h==&hfdcan1) motor_td3_g431_fault_irq(); }
void HAL_COMP_TriggerCallback(COMP_HandleTypeDef *h) { (void)h;motor_td3_g431_fault_irq(); }
void HAL_TIMEx_BreakCallback(TIM_HandleTypeDef *h) { (void)h;motor_td3_g431_fault_irq(); }

static int send_frame(uint32_t id,const uint8_t data[8]) {
    FDCAN_TxHeaderTypeDef h;
    memset(&h,0,sizeof(h));
    if(!HAL_FDCAN_GetTxFifoFreeLevel(&hfdcan1)) return 0;
    h.Identifier=id;h.IdType=FDCAN_STANDARD_ID;h.TxFrameType=FDCAN_DATA_FRAME;
    h.DataLength=FDCAN_DLC_BYTES_8;h.ErrorStateIndicator=FDCAN_ESI_ACTIVE;
    h.BitRateSwitch=FDCAN_BRS_OFF;h.FDFormat=FDCAN_CLASSIC_CAN;h.TxEventFifoControl=FDCAN_NO_TX_EVENTS;
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
    if(tx_inflight) return 0;
    h.TxEventFifoControl=FDCAN_STORE_TX_EVENTS;h.MessageMarker=(uint32_t)(uint8_t)(tx_marker+1U);
#endif
    if(HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1,&h,(uint8_t *)data)!=HAL_OK) { motor_td3_g431_fault_irq();return 0; }
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
    tx_marker=(uint8_t)h.MessageMarker;tx_frame_id=id;tx_queued_us=clock_us();tx_inflight=1;
#endif
    return 1;
}
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
static int tx_completed(uint64_t n) {
    FDCAN_TxEventFifoTypeDef e;
    if(motor_td3_g431_tx_fault) return 0; /* Preserve the first failure/event. */
    /* HAL enqueue success is not transmission completion. Keep one request
     * outstanding and consume its actual Tx event before reusing the FIFO.
     * Nonblocking: foreground health, ADC and RX continue while awaiting ACK. */
    if(!tx_inflight) {
        if(hfdcan1.Instance->TXEFS & FDCAN_TXEFS_EFFL) { motor_td3_g431_tx_fault=1;motor_td3_g431_fault_irq();return 0; }
        return 1;
    }
    if(n-tx_queued_us>=TX_DEADLINE_US) { motor_td3_g431_tx_fault=2;motor_td3_g431_fault_irq();return 0; }
    if(!(hfdcan1.Instance->TXEFS & FDCAN_TXEFS_EFFL)) return 0;
    if(HAL_FDCAN_GetTxEvent(&hfdcan1,&e)!=HAL_OK) { motor_td3_g431_tx_fault=3;motor_td3_g431_fault_irq();return 0; }
    motor_td3_g431_tx_last_event=e;
    if(e.MessageMarker!=tx_marker || e.Identifier!=tx_frame_id || e.EventType!=FDCAN_TX_EVENT ||
       e.IdType!=FDCAN_STANDARD_ID || e.TxFrameType!=FDCAN_DATA_FRAME ||
       e.DataLength!=FDCAN_DLC_BYTES_8 || e.FDFormat!=FDCAN_CLASSIC_CAN || e.BitRateSwitch!=FDCAN_BRS_OFF) {
        motor_td3_g431_tx_fault=4;motor_td3_g431_fault_irq();return 0;
    }
    tx_inflight=0;return 1;
}
#endif
void motor_td3_g431_poll(void) {
    unsigned budget=RX_CAPACITY; int diag_ready=0; uint32_t p;uint8_t frame[8];uint64_t n=clock_us();
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
    uint32_t adc,seq,bad;unsigned owner;
    motor_td3_g431_wd_test_point();
    p=lock();n=now_us;adc=adc_samples;
    owner=endpoint_ready&&(unsigned)endpoint.owner;
    seq=endpoint_ready?endpoint.wire_seq:0;
    bad=irq_fault||(endpoint_ready&&(endpoint.rx_fault||endpoint.protocol_fault));unlock(p);
    if(!motor_td3_g431_wd_service(n,adc,owner,seq,bad)) motor_td3_g431_fault_irq();
#endif
    p=lock();main_seen_us=n;
#ifdef MOTOR_TD3_SPEEDLOOP_PI_MOTION
    (void)p;
#else
    if(!endpoint_ready && motor_td3_g431_debugger_boot_token) {
        const motor_td3_can_hooks h={0,disable_hook,reject_begin,reject_apply,actual_snapshot};
        endpoint_ready=motor_td3_can_control_init_locked(&endpoint,&h,motor_td3_g431_debugger_boot_token,
            LOCKED_FIRMWARE,LOCKED_PROFILE);
        motor_td3_g431_debugger_boot_token=0; /* Consumed, no rearm path. */
    }
#endif
    unlock(p);
    while(endpoint_ready && ring_read!=ring_write && budget--) {
        uint64_t arrived;
        __DMB();memcpy(frame,ring[ring_read%RX_CAPACITY],8);
        arrived=ring_time[ring_read%RX_CAPACITY];
        p=lock();++ring_read;
        /* Packet/queue mutations serialize with SysTick. No HAL or PWM enable here. */
        motor_td3_can_receive(&endpoint,TD3_CAN_REQUEST_ID,1,frame,8,arrived);unlock(p);
    }
    if(!endpoint_ready) return;
#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG
    if(!tx_completed(n)) return;
#endif
    if(!tx_length) {
        int len; p=lock();len=motor_td3_can_make_hello(&endpoint,tx_packet);
        /* SysTick can accept HELLO immediately after unlock. Snapshot permission
         * here so owner cannot become true between the HELLO check and raw TX. */
        diag_ready=endpoint.owner && !endpoint.hello_pending;unlock(p);
        if(len>0) { tx_length=(uint32_t)len;tx_index=0;tx_started_us=n;++tx_transfer; }
    }
    if(tx_length) {
        if(n-tx_started_us>=TX_DEADLINE_US) { motor_td3_g431_fault_irq();tx_length=0;return; }
        if(motor_td3_can_fragment(tx_packet,tx_length,tx_transfer,tx_index,frame) && send_frame(TD3_CAN_RESPONSE_ID,frame)) {
            if(++tx_index>=(tx_length+3)/4) tx_length=0;
        }
        return;
    }
    if(diag_ready && n>=diag_due_us) {
        motor_td3_telemetry t;
        uint8_t hall=(uint8_t)(((GPIOB->IDR>>8)&1U)|((GPIOB->IDR>>6)&2U)|((GPIOB->IDR>>4)&4U));
        actual_snapshot(0,&t);
        if(diag_index==0) {
            uint16_t flags=(uint16_t)((ADC_offset?1:0)|((hall>0&&hall<7)?2:0)|(t.enabled?4:0)|
                (irq_fault?16:0)|(hall_bad?32:0));
            uint64_t seen;uint16_t age;
            p=lock();seen=adc_seen_us;unlock(p);
            age=(uint16_t)((n>=seen?(n-seen)/1000U:0)>65535U?65535U:(n>=seen?(n-seen)/1000U:0));
            frame[0]=1;frame[1]=(uint8_t)endpoint.guard.fault;
            frame[2]=(uint8_t)flags;frame[3]=(uint8_t)(flags>>8);frame[4]=hall;frame[5]=0;
            frame[6]=(uint8_t)age;frame[7]=(uint8_t)(age>>8);
        } else if(diag_index==1) { memcpy(frame,&t.kp,4);memcpy(frame+4,&t.ki,4); }
        else if(diag_index==2) { memcpy(frame,&t.vbus,4);memcpy(frame+4,&t.current,4); }
        else { memcpy(frame,&t.speed,4);memcpy(frame+4,&t.integral_output,4); }
        if(send_frame(0x622U+diag_index,frame) && ++diag_index==4) { diag_index=0;diag_due_us=n+DIAG_PERIOD_US; }
    }
}
