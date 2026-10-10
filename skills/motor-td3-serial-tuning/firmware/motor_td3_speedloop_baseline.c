#include "motor_td3_speedloop_baseline.h"
#include "main.h"
#include "tim.h"
#include "fdcan.h"
#include "FOC_Model.h"
#include "fuzzy_pid.h"
#include <math.h>
#include <string.h>

enum { WAIT=0, READY=1, RUN=2, DONE=3, FAULT=4 };
enum { BREAK_FAULT=1, LINK_FAULT=2, ADC_FAULT=3, BUS_FAULT=4,
       HALL_FAULT=5, OUTPUT_FAULT=6, MAIN_FAULT=7, WATCHDOG_FAULT=8,
       BUTTON_STOP=9, CAN_FAULT=10, EXCEPTION_FAULT=11 };
#define PHASE_MASK 0x555U
#define GPIO_A_MASK ((3U<<16)|(3U<<18)|(3U<<20))
#define GPIO_B_MASK ((3U<<26)|(3U<<28)|(3U<<30))
#define TRIAL_MS 3000U
#define HOST_MAGIC 0x42534C31U
const char motor_td3_baseline_build_id[]="g431-speedloop-baseline-3s-v1";
volatile motor_td3_baseline_record motor_td3_baseline_status;
extern uint8_t Motor_state, ADC_offset;
extern float Ia, Ib, Ic, Vbus, HallSpeed;
static volatile uint32_t button, bus_ms, hall_ms;
static uint32_t last_feed_tick, last_feed_samples, last_button_ms;
static uint32_t last_poll_ms, last_sample_observed, last_sample_ms;
static uint32_t tx_inflight, tx_id, tx_ms, tx_part, tx_due;
static uint8_t tx_marker, snapshot[6][8];
static uint32_t lock(void) { uint32_t p=__get_PRIMASK();__disable_irq();return p; }
static void unlock(uint32_t p) { __set_PRIMASK(p); }
static void pins_low(void) {
    if(RCC->AHB2ENR&RCC_AHB2ENR_GPIOAEN) {
        GPIOA->BSRR=(GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10)<<16;
        GPIOA->MODER=(GPIOA->MODER&~GPIO_A_MASK)|(1U<<16)|(1U<<18)|(1U<<20);
    }
    if(RCC->AHB2ENR&RCC_AHB2ENR_GPIOBEN) {
        GPIOB->BSRR=(GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15)<<16;
        GPIOB->MODER=(GPIOB->MODER&~GPIO_B_MASK)|(1U<<26)|(1U<<28)|(1U<<30);
    }
}
void motor_td3_baseline_off(void) {
    if(RCC->APB2ENR&RCC_APB2ENR_TIM1EN) {
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        TIM1->CCER=0;
        TIM1->CR1 &= ~TIM_CR1_CEN;
    }
    pins_low();__DSB();
    rtU.Motor_OnOff=0;Motor_state=0;
    motor_td3_baseline_status.phase_enabled=0;
}
static void stop(uint32_t reason) {
    uint32_t p=lock();
    motor_td3_baseline_off();
    if(motor_td3_baseline_status.state!=DONE && motor_td3_baseline_status.state!=FAULT) {
        motor_td3_baseline_status.state=reason?FAULT:DONE;
        motor_td3_baseline_status.fault=reason;
    }
    unlock(p);
}
void motor_td3_baseline_fault(uint32_t reason) { stop(reason); }
int motor_td3_baseline_boot(void) {
    motor_td3_baseline_status.magic=HOST_MAGIC;
    motor_td3_baseline_status.reset_flags=RCC->CSR;
    motor_td3_baseline_off();
    if(RCC->CSR&RCC_CSR_IWDGRSTF) {
        motor_td3_baseline_status.state=FAULT;
        motor_td3_baseline_status.fault=WATCHDOG_FAULT;
        return 0; /* Reset cannot restart even by a retained USER3 edge. */
    }
    RCC->CSR|=RCC_CSR_RMVF;return 1;
}
void motor_td3_baseline_init(void) {
    uint32_t began=HAL_GetTick();
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT=0;DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
    /* Keep CH4 ADC timing alive while all six gate pins are driven low. */
    TIM1->CCER&=~PHASE_MASK;pins_low();
    TIM1->DIER|=TIM_DIER_BIE;
    if(!(FLASH->OPTR&FLASH_OPTR_IWDG_SW)) { stop(WATCHDOG_FAULT);return; }
    DBGMCU->APB1FZR1&=~DBGMCU_APB1FZR1_DBG_IWDG_STOP;
    IWDG->KR=0xCCCCU;IWDG->KR=0x5555U;IWDG->PR=3;IWDG->RLR=199;
    while(IWDG->SR) if(HAL_GetTick()-began>=50U) { stop(WATCHDOG_FAULT);return; }
    if(IWDG->WINR!=4095U) IWDG->WINR=4095U;else IWDG->KR=0xAAAAU;
}
void motor_td3_baseline_button(void) { button=1; }
static int ready(uint32_t now) {
    uint32_t code=(GPIOB->IDR>>6)&7U;
    return ADC_offset && motor_td3_baseline_status.samples>=100U &&
        now-motor_td3_baseline_status.last_adc_ms<5U && now-bus_ms<20U &&
        isfinite(Vbus) && Vbus>=18.0f && Vbus<=30.0f && code>0U && code<7U &&
        motor_td3_baseline_status.host_sequence && now-motor_td3_baseline_status.last_host_ms<100U &&
        !(TIM1->SR&(TIM_SR_BIF|TIM_SR_B2IF|TIM_SR_SBIF)) && (TIM1->BDTR&TIM_BDTR_MOE);
}
static void start(uint32_t now) {
    uint32_t p=lock();
    if(motor_td3_baseline_status.state!=READY || !ready(now)) {
        ++motor_td3_baseline_status.rejected_starts;unlock(p);return;
    }
    /* Transfer already configured phase pins while outputs are disconnected,
     * then enable all phase channels in one CCER write. CH4 is independent. */
    TIM1->CCER&=~PHASE_MASK;
    TIM1->CCR1=4000;TIM1->CCR2=4000;TIM1->CCR3=4000;
    TIM1->EGR=TIM_EGR_UG;
    GPIOA->MODER=(GPIOA->MODER&~GPIO_A_MASK)|(2U<<16)|(2U<<18)|(2U<<20);
    GPIOB->MODER=(GPIOB->MODER&~GPIO_B_MASK)|(2U<<26)|(2U<<28)|(2U<<30);
    rtU.SpeedRef=1000;rtU.Motor_OnOff=1;Motor_state=1;
    motor_td3_baseline_status.started_ms=now;
    motor_td3_baseline_status.state=RUN;
    TIM1->CCER|=PHASE_MASK;__DSB();
    motor_td3_baseline_status.phase_enabled=1;
    unlock(p);
}
void motor_td3_baseline_tick(void) {
    uint32_t now=HAL_GetTick();
    if(motor_td3_baseline_status.state!=RUN) return;
    /* HAL_GetTick is the application clock already used by the reference
     * example. Do not make the trial deadline depend on debugger/DWT clock
     * state. */
    motor_td3_baseline_status.elapsed_ms=now-motor_td3_baseline_status.started_ms;
    if(motor_td3_baseline_status.elapsed_ms>=TRIAL_MS) { stop(0);return; }
    if(TIM1->SR&(TIM_SR_BIF|TIM_SR_B2IF|TIM_SR_SBIF)) { stop(BREAK_FAULT);return; }
    if(now-motor_td3_baseline_status.last_host_ms>=100U) { stop(LINK_FAULT);return; }
    if(now-last_poll_ms>=20U) { stop(MAIN_FAULT);return; }
    /* ADC conversion startup can take a few milliseconds after the atomic
     * phase enable. Begin the stale-sample check after that settling window. */
    /* A short gap is possible while the injected conversion and generated
     * FOC step share the CPU. Only a sustained absence of new samples is a
     * fault; the sample counter is observed from the foreground. */
    if(motor_td3_baseline_status.elapsed_ms>=100U &&
       now-last_sample_ms>=100U) { stop(ADC_FAULT);return; }
    if(now-bus_ms>=20U || !isfinite(Vbus) || Vbus<18.0f || Vbus>30.0f) { stop(BUS_FAULT);return; }
    if(motor_td3_baseline_status.elapsed_ms>=2200U &&
       (!motor_td3_baseline_status.hall_edges || now-hall_ms>=100U)) stop(HALL_FAULT);
}
void motor_td3_baseline_adc(void) {
    ++motor_td3_baseline_status.samples;
    motor_td3_baseline_status.last_adc_ms=HAL_GetTick();
    motor_td3_baseline_tick(); /* Deadline also checked if SysTick is starved. */
    /* Raw endpoint values are diagnostic data only. The reference project
     * does not reject a single rail sample; conversion progress and the
     * comparator Break path remain the actual stop conditions. */
}
void motor_td3_baseline_after_step(void) {
    motor_td3_baseline_status.speed_rpm=HallSpeed;
    motor_td3_baseline_status.ia=Ia;motor_td3_baseline_status.ib=Ib;motor_td3_baseline_status.ic=Ic;
    motor_td3_baseline_status.stage=(uint32_t)rtDW.Motor_state;
    motor_td3_baseline_status.kp=spd_kpki.spd_kp;motor_td3_baseline_status.ki=spd_kpki.spd_ki;
    if(motor_td3_baseline_status.state==RUN) {
        float peak=fmaxf(fabsf(Ia),fmaxf(fabsf(Ib),fabsf(Ic)));
        if(!isfinite(peak) || !isfinite(HallSpeed) || !isfinite(rtY.tABC[0]) ||
           !isfinite(rtY.tABC[1]) || !isfinite(rtY.tABC[2]) ||
           rtY.tABC[0]<0 || rtY.tABC[0]>7999 || rtY.tABC[1]<0 ||
           rtY.tABC[1]>7999 || rtY.tABC[2]<0 || rtY.tABC[2]>7999) stop(OUTPUT_FAULT);
        else if(peak>motor_td3_baseline_status.peak_nominal_a) motor_td3_baseline_status.peak_nominal_a=peak;
    }
}
int motor_td3_baseline_hall(uint32_t period,uint32_t code) {
    if(!period || code==0 || code>=7) {
        if(motor_td3_baseline_status.state==RUN) stop(HALL_FAULT);
        return 0;
    }
    ++motor_td3_baseline_status.hall_edges;hall_ms=HAL_GetTick();return 1;
}
void motor_td3_baseline_can_init(void) {
    FDCAN_FilterTypeDef f={0};
    f.IdType=FDCAN_STANDARD_ID;f.FilterIndex=0;f.FilterType=FDCAN_FILTER_MASK;
    f.FilterConfig=FDCAN_FILTER_TO_RXFIFO0;f.FilterID1=0x640;f.FilterID2=0x7FF;
    if(HAL_FDCAN_ConfigFilter(&hfdcan1,&f)!=HAL_OK ||
       HAL_FDCAN_ConfigGlobalFilter(&hfdcan1,FDCAN_REJECT,FDCAN_REJECT,FDCAN_REJECT_REMOTE,FDCAN_REJECT_REMOTE)!=HAL_OK ||
       HAL_FDCAN_Start(&hfdcan1)!=HAL_OK) stop(CAN_FAULT);
}
static void receive(uint32_t now) {
    unsigned budget=3;
    while(budget-- && HAL_FDCAN_GetRxFifoFillLevel(&hfdcan1,FDCAN_RX_FIFO0)) {
        FDCAN_RxHeaderTypeDef h;uint8_t d[8];uint32_t magic,seq;
        if(HAL_FDCAN_GetRxMessage(&hfdcan1,FDCAN_RX_FIFO0,&h,d)!=HAL_OK) { stop(CAN_FAULT);return; }
        if(h.Identifier!=0x640 || h.IdType!=FDCAN_STANDARD_ID || h.RxFrameType!=FDCAN_DATA_FRAME ||
           h.DataLength!=FDCAN_DLC_BYTES_8 || h.FDFormat!=FDCAN_CLASSIC_CAN) continue;
        memcpy(&magic,d,4);memcpy(&seq,d+4,4);
        if(magic==HOST_MAGIC && seq>motor_td3_baseline_status.host_sequence &&
           (motor_td3_baseline_status.state!=RUN || now-motor_td3_baseline_status.last_host_ms<100U)) {
            motor_td3_baseline_status.host_sequence=seq;motor_td3_baseline_status.last_host_ms=now;
        }
    }
}
static void capture(void) {
    uint32_t p=lock();motor_td3_baseline_record s=motor_td3_baseline_status;
    uint16_t elapsed=(uint16_t)s.elapsed_ms, samples=(uint16_t)s.samples;
    memset(snapshot,0,sizeof(snapshot));snapshot[0][0]=0xB1;snapshot[0][1]=(uint8_t)s.state;
    snapshot[0][2]=(uint8_t)s.fault;
    snapshot[0][3]=(uint8_t)(s.stage|((TIM1->BDTR&TIM_BDTR_MOE)&&(TIM1->CCER&PHASE_MASK)?0x80U:0));
    memcpy(snapshot[0]+4,&elapsed,2);memcpy(snapshot[0]+6,&samples,2);
    memcpy(snapshot[1],&s.speed_rpm,4);memcpy(snapshot[1]+4,&s.ia,4);
    memcpy(snapshot[2],&s.ib,4);memcpy(snapshot[2]+4,&s.ic,4);
    memcpy(snapshot[3],&Vbus,4);memcpy(snapshot[3]+4,&s.peak_nominal_a,4);
    memcpy(snapshot[4],&s.kp,4);memcpy(snapshot[4]+4,&s.ki,4);
    memcpy(snapshot[5],&s.host_sequence,4);memcpy(snapshot[5]+4,&s.hall_edges,4);
    unlock(p);
}
static void transmit(uint32_t now) {
    if(!motor_td3_baseline_status.host_sequence) return; /* No ACK/board 5V before the operator powers the board. */
    if(tx_inflight) {
        FDCAN_TxEventFifoTypeDef e;
        if(now-tx_ms>=50U) { stop(CAN_FAULT);return; }
        if(!(hfdcan1.Instance->TXEFS&FDCAN_TXEFS_EFFL)) return;
        if(HAL_FDCAN_GetTxEvent(&hfdcan1,&e)!=HAL_OK || e.MessageMarker!=tx_marker ||
           e.Identifier!=tx_id || e.EventType!=FDCAN_TX_EVENT) { stop(CAN_FAULT);return; }
        tx_inflight=0;
    }
    if(tx_part==0) { if((int32_t)(now-tx_due)<0) return;capture();tx_due=now+20U; }
    if(HAL_FDCAN_GetTxFifoFreeLevel(&hfdcan1)) {
        FDCAN_TxHeaderTypeDef h={0};h.Identifier=0x641U+tx_part;
        h.IdType=FDCAN_STANDARD_ID;h.TxFrameType=FDCAN_DATA_FRAME;h.DataLength=FDCAN_DLC_BYTES_8;
        h.ErrorStateIndicator=FDCAN_ESI_ACTIVE;h.BitRateSwitch=FDCAN_BRS_OFF;h.FDFormat=FDCAN_CLASSIC_CAN;
        h.TxEventFifoControl=FDCAN_STORE_TX_EVENTS;h.MessageMarker=(uint8_t)(tx_marker+1U);
        if(HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1,&h,snapshot[tx_part])!=HAL_OK) { stop(CAN_FAULT);return; }
        tx_marker=(uint8_t)h.MessageMarker;tx_id=h.Identifier;tx_ms=now;tx_inflight=1;
        tx_part=(tx_part+1U)%6U;
    }
}
void motor_td3_baseline_poll(void) {
    uint32_t now=HAL_GetTick();last_poll_ms=now;
    if(motor_td3_baseline_status.samples!=last_sample_observed) {
        last_sample_observed=motor_td3_baseline_status.samples;last_sample_ms=now;
    }
    motor_td3_baseline_tick();receive(now);
    if(motor_td3_baseline_status.state<=READY) motor_td3_baseline_status.state=ready(now)?READY:WAIT;
    if(button) {
        button=0;
        if(now-last_button_ms>=100U) {
            last_button_ms=now;
            if(motor_td3_baseline_status.state==RUN) stop(BUTTON_STOP);
            else if(motor_td3_baseline_status.state==READY) start(now);
            else ++motor_td3_baseline_status.rejected_starts;
        }
    }
    motor_td3_baseline_status.bus_v=Vbus;
    if(now!=last_feed_tick && (motor_td3_baseline_status.state>=DONE ||
       (motor_td3_baseline_status.samples!=last_feed_samples && now-motor_td3_baseline_status.last_adc_ms<5U))) {
        IWDG->KR=0xAAAAU;++motor_td3_baseline_status.feeds;
        last_feed_tick=now;last_feed_samples=motor_td3_baseline_status.samples;
    }
    transmit(now);
}
/* The bus acquisition owner publishes freshness only after both polls succeed. */
void motor_td3_baseline_bus_updated(void) { bus_ms=HAL_GetTick(); }
