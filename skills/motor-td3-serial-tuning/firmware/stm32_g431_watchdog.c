/* SRAM-only IWDG diagnostic. Motor power MUST be physically disconnected.
 * No Flash/option-byte writes, CAN, ADC, GPIO configuration or TIM1 start.
 * Reset vector catch stops the IWDG reset before the Flash app initializes.
 * The heartbeat supervisor is tested separately; this tests hardware reset. */
#include "stm32g431xx.h"
#define MAGIC 0x57444731U
typedef struct {
    uint32_t magic,schema,mode,stage,error,feeds,irq_ticks,irq_at_starve;
    uint32_t healthy_cycles,starve_cycles,spin_cycles,reset_flags_cleared;
    uint32_t dbg_before,dbg_during,option_before,tim_cr1,tim_ccer,tim_bdtr;
    uint32_t gpioa_phase,gpiob_phase,iwdg_pr,iwdg_rlr,iwdg_winr;
} watchdog_box;
static volatile watchdog_box * const box=(volatile watchdog_box *)0x20004400U;
static int isolated(void) {
    return !TIM1->CR1&&!TIM1->CCER&&!TIM1->BDTR&&
        (GPIOA->MODER&0x3F0000U)==0x3F0000U&&
        (GPIOB->MODER&0xFC000000U)==0xFC000000U;
}
void SysTick_Handler(void) { ++box->irq_ticks; } /* Never refresh IWDG in ISR. */
void watchdog_fault(void) {
    box->error|=0x8000U;__disable_irq();while(1) { __NOP(); }
}
static void wait_cycles(uint32_t count) {
    uint32_t begin=DWT->CYCCNT;
    while((uint32_t)(DWT->CYCCNT-begin)<count) { __NOP(); }
}
void watchdog_main(void) {
    uint32_t mode=box->mode,i,begin;
    volatile uint32_t *words=(volatile uint32_t *)box;
    for(i=0;i<sizeof(*box)/4;i++) words[i]=0;
    box->mode=mode;box->magic=MAGIC;box->schema=1;box->stage=1;
    box->option_before=FLASH->OPTR;box->dbg_before=DBGMCU->APB1FZR1;
    if((mode!=1&&mode!=2)||!(FLASH->OPTR&FLASH_OPTR_IWDG_SW)||
       (RCC->CFGR&RCC_CFGR_SWS)!=RCC_CFGR_SWS_HSI||!(RCC->CR&RCC_CR_HSIRDY)) {
        box->error=1;return;
    }
    /* Clock enables permit register inspection; no GPIO modes or PWM changed. */
    RCC->AHB2ENR|=RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN;
    RCC->APB2ENR|=RCC_APB2ENR_TIM1EN;__DSB();
    if(!isolated()) { box->error=1;return; }
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk|CoreDebug_DEMCR_VC_CORERESET_Msk;
    SCB->VTOR=0x20000000U;__DSB();__ISB();
    DWT->CYCCNT=0;DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
    /* Clear previous reset evidence before starting this test. */
    RCC->CSR|=RCC_CSR_RMVF;box->reset_flags_cleared=RCC->CSR;
    DBGMCU->APB1FZR1&=~DBGMCU_APB1FZR1_DBG_IWDG_STOP;
    box->dbg_during=DBGMCU->APB1FZR1;
    SysTick->LOAD=15999U;SysTick->VAL=0;SysTick->CTRL=7;
    __enable_irq();
    IWDG->KR=0xCCCCU;IWDG->KR=0x5555U;IWDG->PR=3;IWDG->RLR=199;
    begin=DWT->CYCCNT;
    while(IWDG->SR) {
        if((uint32_t)(DWT->CYCCNT-begin)>800000U) { box->error=2;return; }
    }
    if(IWDG->WINR!=4095U) IWDG->WINR=4095U;
    else IWDG->KR=0xAAAAU;
    box->iwdg_pr=IWDG->PR;box->iwdg_rlr=IWDG->RLR;box->iwdg_winr=IWDG->WINR;
    begin=DWT->CYCCNT;
    for(i=0;i<60;i++) {
        wait_cycles(160000U); /* Reset HSI16 clock: about 10ms. */
        if(!isolated()) { box->error=4;return; }
        IWDG->KR=0xAAAAU;++box->feeds;
    }
    box->healthy_cycles=DWT->CYCCNT-begin;box->irq_at_starve=box->irq_ticks;
    box->tim_cr1=TIM1->CR1;box->tim_ccer=TIM1->CCER;box->tim_bdtr=TIM1->BDTR;
    box->gpioa_phase=GPIOA->MODER&0x3F0000U;
    box->gpiob_phase=GPIOB->MODER&0xFC000000U;
    if(mode==2) __disable_irq();
    box->stage=2;box->starve_cycles=DWT->CYCCNT;
    /* Simulate failed foreground. SysTick in mode1 remains alive, with no feed.
     * Mode2 also removes all maskable interrupts, including SysTick. */
    while(1) {
        box->spin_cycles=DWT->CYCCNT-box->starve_cycles;
        if(box->spin_cycles>32000000U) { box->error=8;__BKPT(0); }
    }
}
