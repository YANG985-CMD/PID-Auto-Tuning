#include "main.h"
#include "motor_td3_speedloop_baseline.h"
#include "fdcan.h"
#include "FOC_Model.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
TIM_TypeDef fake_tim;
RCC_TypeDef fake_rcc;
GPIO_TypeDef fake_a,fake_b;
ADC_TypeDef fake_adc1,fake_adc2;
DWT_Type fake_dwt;
CoreDebug_Type fake_debug;
DBGMCU_TypeDef fake_dbgmcu;
IWDG_TypeDef fake_iwdg;
FLASH_TypeDef fake_flash;
FDCAN_GlobalTypeDef fake_can;
FDCAN_HandleTypeDef hfdcan1;
uint32_t SystemCoreClock=160000000U;
uint8_t Motor_state,ADC_offset=1;
float Ia,Ib,Ic,Vbus=24,HallSpeed;
ExtU rtU;
ExtY rtY;
DW rtDW;
spd_kpki_type spd_kpki;
static uint32_t now,seq,pending;
static FDCAN_TxEventFifoTypeDef event;
uint32_t HAL_GetTick(void) { return now; }
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *h,FDCAN_FilterTypeDef *f) { (void)h;(void)f;return HAL_OK; }
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *h,uint32_t a,uint32_t b,uint32_t c,uint32_t d) {
    (void)h;(void)a;(void)b;(void)c;(void)d;return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *h) { (void)h;return HAL_OK; }
uint32_t HAL_FDCAN_GetRxFifoFillLevel(FDCAN_HandleTypeDef *h,uint32_t fifo) { (void)h;(void)fifo;return pending; }
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *h,uint32_t fifo,FDCAN_RxHeaderTypeDef *rx,uint8_t *d) {
    uint32_t magic=0x42534c31;(void)h;(void)fifo;memset(rx,0,sizeof(*rx));
    rx->Identifier=0x640;rx->IdType=FDCAN_STANDARD_ID;rx->RxFrameType=FDCAN_DATA_FRAME;
    rx->DataLength=FDCAN_DLC_BYTES_8;rx->FDFormat=FDCAN_CLASSIC_CAN;
    memcpy(d,&magic,4);memcpy(d+4,&seq,4);pending=0;return HAL_OK;
}
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(FDCAN_HandleTypeDef *h) { (void)h;return 1; }
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *h,FDCAN_TxHeaderTypeDef *tx,uint8_t *d) {
    (void)h;(void)d;memset(&event,0,sizeof(event));event.Identifier=tx->Identifier;
    event.MessageMarker=tx->MessageMarker;event.EventType=FDCAN_TX_EVENT;
    fake_can.TXEFS=1;return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_GetTxEvent(FDCAN_HandleTypeDef *h,FDCAN_TxEventFifoTypeDef *e) {
    (void)h;*e=event;fake_can.TXEFS=0;return HAL_OK;
}
static void heartbeat(void) { ++seq;pending=1; }
static void advance(unsigned count,int link) {
    while(count--) {
        ++now;fake_dwt.CYCCNT=now*160000U;
        if(link && now%20==0) heartbeat();
        motor_td3_baseline_bus_updated();
        motor_td3_baseline_adc();motor_td3_baseline_poll();
    }
}
static void off_check(void) {
    assert(!(fake_tim.BDTR&TIM_BDTR_MOE));assert(fake_tim.CCER==0);assert(!(fake_tim.CR1&TIM_CR1_CEN));
    assert(!rtU.Motor_OnOff && !Motor_state && !motor_td3_baseline_status.phase_enabled);
    assert((fake_a.MODER&((3U<<16)|(3U<<18)|(3U<<20)))==((1U<<16)|(1U<<18)|(1U<<20)));
    assert((fake_b.MODER&((3U<<26)|(3U<<28)|(3U<<30)))==((1U<<26)|(1U<<28)|(1U<<30)));
}
int main(int argc,char **argv) {
    int test=argc==2?atoi(argv[1]):0;
    fake_rcc.AHB2ENR=RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN;
    fake_rcc.APB2ENR=RCC_APB2ENR_TIM1EN;fake_flash.OPTR=FLASH_OPTR_IWDG_SW;
    hfdcan1.Instance=&fake_can;fake_b.IDR=5U<<6;
    fake_adc1.JDR1=fake_adc1.JDR2=fake_adc2.JDR1=2024;
    assert(motor_td3_baseline_boot());off_check();
    fake_tim.CR1=TIM_CR1_CEN;fake_tim.CCER=TIM_CCER_CC4E;fake_tim.BDTR=TIM_BDTR_MOE;
    motor_td3_baseline_init();motor_td3_baseline_can_init();
    advance(200,test!=1);
    if(test==2) Vbus=0;
    motor_td3_baseline_poll();motor_td3_baseline_button();motor_td3_baseline_poll();
    if(test==1 || test==2) {
        assert(motor_td3_baseline_status.state==0);assert(!(fake_tim.CCER&0x555U));
    } else {
        assert(motor_td3_baseline_status.state==2);assert((fake_tim.CCER&0x555U)==0x555U);
        assert(rtU.SpeedRef==1000 && rtU.Motor_OnOff==1);
        if(test==3) { fake_tim.SR=TIM_SR_BIF;motor_td3_baseline_tick(); }
        else if(test==4) { now+=60;fake_dwt.CYCCNT=now*160000U;motor_td3_baseline_poll(); }
        else if(test==5) advance(101,0);
        else if(test==6) motor_td3_baseline_hall(0,0);
        else if(test==7) {
            now+=21;fake_dwt.CYCCNT=now*160000U;motor_td3_baseline_adc();
        } else {
            for(unsigned i=0;i<3000;++i) {
                if(i%10==0) assert(motor_td3_baseline_hall(1000,5));
                advance(1,1);
            }
            assert(motor_td3_baseline_status.state==3 && motor_td3_baseline_status.elapsed_ms==3000);
        }
        off_check();
        advance(200,1);motor_td3_baseline_button();motor_td3_baseline_poll();off_check();
        assert(motor_td3_baseline_status.state>=3); /* Fresh link and USER3 cannot restart a completed/failed trial. */
    }
    printf("case %d passed\n",test);return 0;
}
