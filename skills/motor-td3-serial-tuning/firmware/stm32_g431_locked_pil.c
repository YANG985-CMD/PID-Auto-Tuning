/* SRAM-only test of the SHARED TIM1 disable helper and locked CAN endpoint.
 * Not the full HAL/FOC adapter. PI values and commands are test fixtures.
 * No external CAN, ADC, pin configuration, phase PWM or Flash programming.
 * A clocked TIM1 CCER is seeded ONLY while MOE=0 and pins remain reset analog.
 * This tests clearing real phase bits without producing a motor waveform. */
#include "motor_td3_g431_off.h"
#include "motor_td3_can_control.h"
#include "locked_pil_vectors.h"
#include <math.h>
#include <string.h>

typedef struct {
    uint32_t magic,schema,state,error,cases,passed,rejected_mask,disable_calls;
    uint32_t systick_count,tim1_ccer,tim1_bdtr,gpio_clock,rcc_apb2enr,callback_calls;
} mailbox;
static volatile mailbox * const box=(volatile mailbox *)0x20004400U;
static motor_td3_can_control ctx;
static uint32_t begin_calls,apply_calls;
static volatile uint32_t ticks;
static uint64_t step_time;
static int timer_ready;
static void off(void *u) { (void)u;motor_td3_g431_outputs_off();++box->disable_calls; }
static int begin(void *u,float r,float kp,float ki) { (void)u;(void)r;(void)kp;(void)ki;++begin_calls;return 0; }
static int apply(void *u,float kp,float ki) { (void)u;(void)kp;(void)ki;++apply_calls;return 0; }
static int snapshot(void *u,motor_td3_telemetry *t) {
    (void)u;memset(t,0,sizeof(*t));t->enabled=motor_td3_g431_outputs_enabled()!=0;
    t->kp=.003389F;t->ki=.00144F;t->temperature_c=NAN;return 1;
}
static void check(int ok,uint32_t bit) { ++box->cases;if(ok)++box->passed;else box->error|=bit; }
static void deliver(const uint8_t *packet,unsigned length,uint8_t tag) {
    uint8_t frame[8];unsigned i;
    for(i=0;i<(length+3)/4;i++) {
        if(!motor_td3_can_fragment(packet,length,tag,i,frame) ||
           motor_td3_can_receive(&ctx,0x620,1,frame,8,step_time)<0) box->error|=0x8000U;
    }
    motor_td3_can_control_tick(&ctx,step_time,1);++step_time;
}
void locked_pil_systick(void) {
    ++ticks;motor_td3_g431_outputs_off();
    if(timer_ready) motor_td3_can_control_tick(&ctx,step_time+(uint64_t)ticks*1000U,1);
}
void locked_pil_main(void) {
    uint8_t packet[TD3_CAN_MAX_PACKET],frame[8];int len;
    const motor_td3_can_hooks hooks={0,off,begin,apply,snapshot};
    SCB->CPACR|=0x00F00000U;__DSB();__ISB();
    box->magic=0x474C4B31U;box->schema=1;box->state=1;
    check((RCC->AHB2ENR&0x7fU)==0 && TIM1->BDTR==0 && TIM1->CCER==0,1);
    if(box->error) { box->state=3;return; }
    off(0);check(TIM1->BDTR==0&&TIM1->CCER==0,2);
    RCC->APB2ENR|=RCC_APB2ENR_TIM1EN;__DSB();
    TIM1->BDTR&=~TIM_BDTR_MOE;
    TIM1->CCER=TD3_G431_PHASE_MASK|TIM_CCER_CC4E;
    off(0);
    check(!(TIM1->BDTR&TIM_BDTR_MOE)&&TIM1->CCER==TIM_CCER_CC4E,4);
    check(motor_td3_can_control_init_locked(&ctx,&hooks,LOCKED_TEST_BOOT,
        "g431-foc-can-locked-v1","g431-foc-locked-v1") && ctx.guard.fault==TD3_CAN_NOT_READY && !ctx.capabilities,8);
    step_time=1000;
    deliver(locked_hello,sizeof(locked_hello),1);len=motor_td3_can_make_hello(&ctx,packet);
    check(len>36&&!packet[32]&&!packet[33]&&ctx.owner,16);
    deliver(locked_begin,sizeof(locked_begin),2);
    if(!ctx.guard.enabled&&!begin_calls) box->rejected_mask|=1;
    check((box->rejected_mask&1U)&&!motor_td3_g431_outputs_enabled(),32);
    deliver(locked_gains,sizeof(locked_gains),3);
    if(!ctx.guard.enabled&&!apply_calls&&!ctx.guard.applied_seq) box->rejected_mask|=2;
    check((box->rejected_mask&2U)&&!motor_td3_g431_outputs_enabled(),64);
    check(motor_td3_can_make_telemetry(&ctx,packet)==0,128);
    deliver(locked_stop,sizeof(locked_stop),4);
    check(!ctx.guard.enabled&&ctx.guard.fault==TD3_CAN_NOT_READY,256);
    /* A partial packet then no CAN/ADC/main service: real SysTick must advance
     * timeout handling and repeatedly clear the seeded phase bits with MOE=0. */
    motor_td3_can_fragment(locked_hello,sizeof(locked_hello),5,0,frame);
    motor_td3_can_receive(&ctx,0x620,1,frame,8,step_time);
    TIM1->CCER=TD3_G431_PHASE_MASK|TIM_CCER_CC4E;
    timer_ready=1;SysTick->LOAD=16000U-1U;SysTick->VAL=0;SysTick->CTRL=7;
    __enable_irq();while(ticks<55) { __WFI(); }__disable_irq();SysTick->CTRL=0;
    check(ticks>=55 && TIM1->CCER==TIM_CCER_CC4E && ctx.rx_fault,512);
    check(begin_calls==0&&apply_calls==0&&!(TIM1->BDTR&TIM_BDTR_MOE)&&(RCC->AHB2ENR&0x7fU)==0,1024);
    TIM1->CCER=0;TIM1->BDTR=0;TIM1->CR1=0;RCC->APB2ENR&=~RCC_APB2ENR_TIM1EN;
    box->systick_count=ticks;box->callback_calls=begin_calls+apply_calls;
    box->tim1_ccer=TIM1->CCER;box->tim1_bdtr=TIM1->BDTR;
    box->gpio_clock=RCC->AHB2ENR&0x7fU;box->rcc_apb2enr=RCC->APB2ENR;
    box->state=box->error?3U:2U;
}
