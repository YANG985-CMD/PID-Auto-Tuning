/* Static three-phase ADC zero observation. Power must be disconnected.
 * Never enables TIM1, PWM channels or alternate-function phase pins.
 * Regular software conversions at 4MHz, 247.5-cycle sampling do not reproduce
 * the original FOC injected/timer-triggered acquisition timing.
 */
#include "stm32g431xx.h"

#define MAGIC 0x435A5231U
#define A_PHASE_MODE 0x003F0000U
#define B_PHASE_MODE 0xFC000000U
#define NROWS 64U
#define WAIT_LIMIT 160000U
/* Factory trims are automatically present on readback with USERTRIM=0.
 * OUTCAL is a status bit; all configuration and lock bits remain checked. */
#define OPAMP_CONFIG_MASK (~(OPAMP_CSR_TRIMOFFSETP|OPAMP_CSR_TRIMOFFSETN|OPAMP_CSR_OUTCAL))
typedef struct {
    uint32_t magic,schema,state,error,cases,passed,samples,unsafe_samples,cycles;
    uint32_t adc1_calfact,adc2_calfact,adc_common,adc1_smpr1,adc1_smpr2,adc2_smpr1;
    uint32_t adc1_cfgr,adc2_cfgr,opamp1_csr,opamp2_csr,opamp3_csr;
    uint32_t gpioa_phase_mode,gpiob_phase_mode,tim_cr1,tim_ccer,tim_bdtr,gpio_clocks;
    uint32_t last_adc1_isr,last_adc2_isr;
} mailbox_t;
typedef struct { uint32_t a,b,c,safe; } row_t;
static volatile mailbox_t *const box=(mailbox_t *)0x20004400U;
static volatile row_t *const rows=(row_t *)0x20004500U;

static int isolated(void) {
    int ok=!TIM1->CR1&&!TIM1->CCER&&!TIM1->BDTR&&
        (GPIOA->MODER&A_PHASE_MODE)==A_PHASE_MODE&&
        (GPIOB->MODER&B_PHASE_MODE)==B_PHASE_MODE;
    if(!ok)++box->unsafe_samples;
    return ok;
}
static void delay(uint32_t cycles) {
    uint32_t start=DWT->CYCCNT;
    while((uint32_t)(DWT->CYCCNT-start)<cycles) { __NOP(); }
}
static int wait_bits(volatile uint32_t *reg,uint32_t mask,uint32_t value) {
    uint32_t start=DWT->CYCCNT;
    while((*reg&mask)!=value) {
        if((uint32_t)(DWT->CYCCNT-start)>=WAIT_LIMIT)return 0;
    }
    return 1;
}
static void check(int ok,uint32_t bit) {
    ++box->cases;if(ok)++box->passed;else box->error|=bit;
}
static int adc_init(ADC_TypeDef *adc) {
    /* Factory hardware single-ended calibration, distinct from current zero. */
    adc->CR=ADC_CR_ADVREGEN;delay(16000U);
    adc->CFGR=0;adc->CFGR2=0;adc->DIFSEL=0;
    adc->CR|=ADC_CR_ADCAL;
    if(!wait_bits(&adc->CR,ADC_CR_ADCAL,0))return 0;
    delay(16000U); /* exceeds four ADC cycles after calibration */
    adc->ISR=ADC_ISR_ADRDY;adc->CR|=ADC_CR_ADEN;
    return wait_bits(&adc->ISR,ADC_ISR_ADRDY,ADC_ISR_ADRDY);
}
static int convert(ADC_TypeDef *adc,uint32_t channel,uint32_t *value) {
    if(adc->CR&(ADC_CR_ADSTART|ADC_CR_JADSTART))return 0;
    adc->SQR1=channel<<ADC_SQR1_SQ1_Pos;
    adc->ISR=ADC_ISR_EOC|ADC_ISR_EOS|ADC_ISR_OVR;
    adc->CR|=ADC_CR_ADSTART;
    if(!wait_bits(&adc->ISR,ADC_ISR_EOC,ADC_ISR_EOC))return 0;
    *value=adc->DR;
    return !(adc->ISR&ADC_ISR_OVR)&&*value<=4095U&&
        wait_bits(&adc->CR,ADC_CR_ADSTART,0);
}
static int triple(uint32_t *a,uint32_t *b,uint32_t *c) {
    return convert(ADC1,3U,a)&&convert(ADC2,3U,b)&&convert(ADC1,12U,c);
}
static void shutdown(void) {
    box->last_adc1_isr=ADC1->ISR;box->last_adc2_isr=ADC2->ISR;
    /* Reset ADCs also terminates an unfinished conversion on an error path. */
    RCC->AHB2RSTR|=RCC_AHB2RSTR_ADC12RST;__DSB();
    RCC->AHB2RSTR&=~RCC_AHB2RSTR_ADC12RST;__DSB();
    OPAMP1->CSR=0;OPAMP2->CSR=0;OPAMP3->CSR=0;
    RCC->APB2ENR&=~RCC_APB2ENR_SYSCFGEN;
    RCC->AHB2ENR&=~(RCC_AHB2ENR_ADC12EN|RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN);
    box->tim_cr1=TIM1->CR1;box->tim_ccer=TIM1->CCER;box->tim_bdtr=TIM1->BDTR;
    box->gpio_clocks=RCC->AHB2ENR;
    check(!box->tim_cr1&&!box->tim_ccer&&!box->tim_bdtr&&!box->gpio_clocks,64U);
}
void current_zero_main(void) {
    uint32_t begin,i,a=0,b=0,c=0;
    box->magic=MAGIC;box->schema=1;box->state=1;
    if((RCC->CFGR&RCC_CFGR_SWS)!=RCC_CFGR_SWS_HSI||
        !(RCC->CR&RCC_CR_HSIRDY)||TIM1->CR1||TIM1->CCER||TIM1->BDTR||RCC->AHB2ENR) {
        box->error=0x20000U;box->state=3;return;
    }
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT=0;DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;begin=DWT->CYCCNT;
    RCC->AHB2ENR|=RCC_AHB2ENR_GPIOAEN|RCC_AHB2ENR_GPIOBEN|RCC_AHB2ENR_ADC12EN;
    RCC->APB2ENR|=RCC_APB2ENR_SYSCFGEN;__DSB();
    check(isolated()&&(GPIOA->MODER&0xFF0U)==0xFF0U&&
        (GPIOB->MODER&0x3FU)==0x3FU,1U);
    if(box->error)goto done;
    OPAMP1->CSR=OPAMP_CSR_OPAMPxEN;OPAMP2->CSR=OPAMP_CSR_OPAMPxEN;
    OPAMP3->CSR=OPAMP_CSR_OPAMPxEN;delay(16000U);
    ADC12_COMMON->CCR=ADC_CCR_CKMODE_1|ADC_CCR_CKMODE_0; /* HCLK/4 */
    check(adc_init(ADC1),2U);if(box->error)goto done;
    check(adc_init(ADC2),4U);if(box->error)goto done;
    ADC1->SMPR1=6U<<ADC_SMPR1_SMP3_Pos;
    ADC1->SMPR2=6U<<ADC_SMPR2_SMP12_Pos;
    ADC2->SMPR1=6U<<ADC_SMPR1_SMP3_Pos;
    box->adc1_calfact=ADC1->CALFACT;box->adc2_calfact=ADC2->CALFACT;
    box->adc_common=ADC12_COMMON->CCR;
    box->adc1_smpr1=ADC1->SMPR1;box->adc1_smpr2=ADC1->SMPR2;box->adc2_smpr1=ADC2->SMPR1;
    box->adc1_cfgr=ADC1->CFGR;box->adc2_cfgr=ADC2->CFGR;
    box->opamp1_csr=OPAMP1->CSR;box->opamp2_csr=OPAMP2->CSR;box->opamp3_csr=OPAMP3->CSR;
    box->gpioa_phase_mode=GPIOA->MODER&A_PHASE_MODE;
    box->gpiob_phase_mode=GPIOB->MODER&B_PHASE_MODE;
    check(box->adc_common==0x30000U&&box->adc1_smpr1==0xC00U&&
        box->adc1_smpr2==0x180U&&box->adc2_smpr1==0xC00U&&
        !box->adc1_cfgr&&!box->adc2_cfgr&&(box->opamp1_csr&OPAMP_CONFIG_MASK)==1U&&
        (box->opamp2_csr&OPAMP_CONFIG_MASK)==1U&&(box->opamp3_csr&OPAMP_CONFIG_MASK)==1U,8U);
    if(box->error)goto done;
    for(i=0;i<16U;i++) { /* discard startup/channel settling samples */
        if(!triple(&a,&b,&c)||!isolated()) { box->error|=0x10000U;goto done; }
    }
    for(i=0;i<NROWS;i++) {
        if(!triple(&a,&b,&c)) { box->error|=0x10000U;goto done; }
        rows[i].a=a;rows[i].b=b;rows[i].c=c;rows[i].safe=(uint32_t)isolated();
        box->samples=i+1U;delay(1600U);
        if(box->unsafe_samples)goto done;
    }
    check(box->samples==NROWS&&!box->unsafe_samples,16U);
    check(!(ADC1->ISR&ADC_ISR_OVR)&&!(ADC2->ISR&ADC_ISR_OVR)&&isolated(),32U);
done:
    box->cycles=DWT->CYCCNT-begin;
    shutdown();box->state=box->error?3U:2U;
}
