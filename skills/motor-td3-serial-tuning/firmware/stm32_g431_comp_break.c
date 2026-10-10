/* Dedicated SRAM diagnostic, NOT a motor application or current calibration.
 * Requires physically disconnected motor power. Changes internal DAC3 CH1
 * threshold against the stationary OPAMP3/PB1 input; observes COMP1 and BIF.
 * Never sets MOE, CCER, CEN or a GPIO mode. No pin PWM, CAN, ADC or Flash write.
 * Thus it cannot prove MOE was cleared from 1 or measure output shutoff delay. */
#include "motor_td3_g431_off.h"

#define MAGIC 0x43425231U
#define A_PHASE_MODE (0x3FU<<16)
#define B_PHASE_MODE (0x3FU<<26)
#define BDTR_CONFIG (120U|TIM_BDTR_BKE|TIM_BDTR_BKP|(2U<<TIM_BDTR_BKF_Pos))
#define COMP_CONFIG (COMP_CSR_INPSEL|COMP_CSR_INMSEL_2|COMP_CSR_EN)
#define MAX_SAMPLES 24U
typedef struct {
    uint32_t magic,schema,state,error,cases,passed,fault_latched,unsafe_samples;
    uint32_t samples,cycles,transition_low,transition_high,recovery_sr,recovery_latch;
    uint32_t comp_config,dac_mode,tim_route,tim_break_config;
    uint32_t gpioa_phase_mode,gpiob_phase_mode;
    uint32_t tim_cr1,tim_ccer,tim_bdtr,gpio_clocks;
} mailbox;
typedef struct { uint32_t dac,comp_csr,tim_sr,safe; } row;
static volatile mailbox * const box=(volatile mailbox *)0x20004400U;
static volatile row * const rows=(volatile row *)0x20004500U;

static int isolated(void) {
    int ok=!(TIM1->CR1&TIM_CR1_CEN)&&!TIM1->CCER&&!(TIM1->BDTR&TIM_BDTR_MOE)&&
        (GPIOA->MODER&A_PHASE_MODE)==A_PHASE_MODE&&
        (GPIOB->MODER&B_PHASE_MODE)==B_PHASE_MODE;
    if(!ok) { ++box->unsafe_samples;motor_td3_g431_outputs_off();TIM1->CR1=0; }
    return ok;
}
static void settle(void) {
    uint32_t start=DWT->CYCCNT;
    while((uint32_t)(DWT->CYCCNT-start)<16000U) { __NOP(); }
}
static void check(int ok,uint32_t bit) {
    ++box->cases;if(ok)++box->passed;else box->error|=bit;
}
static uint32_t sample(uint32_t code) {
    uint32_t i=box->samples;
    DAC3->DHR12R1=code;settle();
    if(i>=MAX_SAMPLES) { box->error|=0x10000U;return 0; }
    rows[i].dac=code;rows[i].comp_csr=COMP1->CSR;
    rows[i].tim_sr=TIM1->SR;rows[i].safe=(uint32_t)isolated();
    box->samples=i+1U;
    return (rows[i].comp_csr&COMP_CSR_VALUE)!=0U;
}
static void shutdown(void) {
    motor_td3_g431_outputs_off();TIM1->CR1=0;TIM1->CCER=0;TIM1->BDTR=0;
    TIM1->AF1=0;TIM1->SR=0;COMP1->CSR=0;OPAMP3->CSR=0;DAC3->CR=0;
    RCC->APB2ENR&=~(RCC_APB2ENR_TIM1EN|RCC_APB2ENR_SYSCFGEN);
    RCC->AHB2ENR&=~(RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN|RCC_AHB2ENR_DAC3EN);
    box->tim_cr1=TIM1->CR1;box->tim_ccer=TIM1->CCER;box->tim_bdtr=TIM1->BDTR;
    box->gpio_clocks=RCC->AHB2ENR;
}
void comp_break_main(void) {
    uint32_t begin,lo=0,hi=4095,i,level;
    box->magic=MAGIC;box->schema=1;box->state=1;
    /* Reset clock must be 16MHz HSI; do not guess settling or cycle units. */
    if((RCC->CFGR&RCC_CFGR_SWS)!=RCC_CFGR_SWS_HSI ||
        !(RCC->CR&RCC_CR_HSIRDY) || TIM1->CR1||TIM1->CCER||TIM1->BDTR||RCC->AHB2ENR) {
        box->error=0x20000U;box->state=3;return;
    }
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT=0;DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;begin=DWT->CYCCNT;
    RCC->AHB2ENR|=RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN|RCC_AHB2ENR_DAC3EN;
    RCC->APB2ENR|=RCC_APB2ENR_TIM1EN|RCC_APB2ENR_SYSCFGEN;__DSB();
    check(isolated()&&(GPIOB->MODER&0x3FU)==0x3FU,1);
    if(box->error) { shutdown();box->state=3;return; }
    /* Same standalone external-feedback OPAMP3 mode as the audited board. */
    OPAMP3->CSR=OPAMP_CSR_OPAMPxEN;settle();
    DAC3->MCR=DAC_MCR_MODE1_0|DAC_MCR_MODE1_1; /* internal, buffer disabled */
    DAC3->DHR12R1=4095;DAC3->CR=DAC_CR_EN1;settle();
    COMP1->CSR=COMP_CONFIG;settle();
    TIM1->AF1=TIM1_AF1_BKCMP1E;TIM1->BDTR=BDTR_CONFIG;
    TIM1->SR=0;settle();
    box->comp_config=COMP1->CSR&~COMP_CSR_VALUE;box->dac_mode=DAC3->MCR;
    box->tim_route=TIM1->AF1;box->tim_break_config=TIM1->BDTR;
    box->gpioa_phase_mode=GPIOA->MODER&A_PHASE_MODE;
    box->gpiob_phase_mode=GPIOB->MODER&B_PHASE_MODE;
    check(box->comp_config==COMP_CONFIG&&box->dac_mode==3U&&
        box->tim_route==TIM1_AF1_BKCMP1E&&box->tim_break_config==BDTR_CONFIG&&
        (DAC3->SR&DAC_SR_DAC1RDY),2);
    level=sample(4095);check(!level&&!motor_td3_g431_break_seen(),4);
    level=sample(3000);check(!level&&!motor_td3_g431_break_seen(),8);
    level=sample(0);
    if(motor_td3_g431_break_seen()) { box->fault_latched=1;motor_td3_g431_outputs_off(); }
    check(level&&(TIM1->SR&TIM_SR_BIF)&&box->fault_latched,16);
    /* Return the comparator to low, then clear only the diagnostic HW flag.
     * The software latch stays set; the actual adapter is separately tested. */
    level=sample(4095);TIM1->SR=0;settle();
    box->recovery_sr=TIM1->SR;box->recovery_latch=box->fault_latched;
    check(!level&&!motor_td3_g431_break_seen()&&box->fault_latched,32);
    for(i=0;i<12;i++) {
        uint32_t mid=(lo+hi)/2U;
        if(sample(mid)) lo=mid;else hi=mid;
    }
    box->transition_low=lo;box->transition_high=hi;
    check(lo>0U&&hi<3000U&&hi==lo+1U,64);
    sample(4095);TIM1->SR=0;settle();
    check(!box->unsafe_samples&&box->fault_latched&&isolated()&&
        !(TIM1->BDTR&TIM_BDTR_AOE)&&!TIM1->DIER,128);
    box->cycles=DWT->CYCCNT-begin;
    shutdown();box->state=box->error?3U:2U;
}
