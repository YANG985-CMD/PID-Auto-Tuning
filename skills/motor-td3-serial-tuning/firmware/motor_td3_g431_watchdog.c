/* Diagnostic-only integration. TIM1 never starts in this build. */
#include "motor_td3_g431_watchdog.h"
#include "motor_td3_health.h"
#include "motor_td3_g431_adapter.h"
#include "stm32g431xx.h"
volatile motor_td3_g431_wd_record motor_td3_g431_wd_status;
volatile uint32_t motor_td3_g431_wd_test_mode;
static motor_td3_health health;
static uint64_t main_sequence;
extern uint32_t HAL_GetTick(void);
/* Diagnostic scheduling limits, not motor safety acceptance thresholds. */
static const motor_td3_health_limits limits={5000,5000,30000,200000};
static void off(void) {
    motor_td3_g431_disable();
    if(RCC->APB2ENR&RCC_APB2ENR_TIM1EN) {
        TIM1->CCER=0;TIM1->CR1&=~TIM_CR1_CEN;__DSB();
    }
}
int motor_td3_g431_wd_boot_check(void) {
    motor_td3_g431_wd_status.magic=0x53445731U;
    motor_td3_g431_wd_status.reset_flags=RCC->CSR;
    off();
    if(RCC->CSR&RCC_CSR_IWDGRSTF) {
        motor_td3_g431_wd_status.boot_latched=1;
        return 1; /* Remain in reset-safe foreground hold; no peripherals/start. */
    }
    RCC->CSR|=RCC_CSR_RMVF;
    return 0;
}
int motor_td3_g431_wd_init(uint64_t now) {
    uint32_t started;
    off();
    if(motor_td3_g431_wd_status.active||motor_td3_g431_wd_status.boot_latched||
       !(FLASH->OPTR&FLASH_OPTR_IWDG_SW)) return 0;
    /* A debugger must not hide a stalled-foreground watchdog failure. */
    DBGMCU->APB1FZR1&=~DBGMCU_APB1FZR1_DBG_IWDG_STOP;
    IWDG->KR=0xCCCCU;IWDG->KR=0x5555U;IWDG->PR=3;IWDG->RLR=199;
    started=(uint32_t)now;
    while(IWDG->SR) {
        /* HAL tick is live here; independent IWDG still resets if IRQs stop. */
        if((uint32_t)(HAL_GetTick()*1000U-started)>=50000U) return 0;
    }
    if(IWDG->WINR!=4095U) IWDG->WINR=4095U;
    else IWDG->KR=0xAAAAU;
    /* Register synchronization precedes foreground/ADC deadline accounting. */
    now=(uint64_t)HAL_GetTick()*1000U;
    if(!motor_td3_health_init(&health,&limits,now)) return 0;
    main_sequence=0;
    motor_td3_g431_wd_status.active=1;
    return 1;
}
int motor_td3_g431_wd_service(uint64_t now,uint32_t adc,unsigned owner,
                             uint32_t validated_stop_seq,unsigned board_fault) {
    uint64_t tick=now/1000U;
    if(!motor_td3_g431_wd_status.active) { off();return 0; }
    /* Check before refreshing. A late frame/sample cannot revive this state. */
    motor_td3_health_check(&health,now);
    if(board_fault) motor_td3_health_board_fault(&health);
    if(!health.fault) {
        motor_td3_health_progress(&health,TD3_HEALTH_MAIN,now,++main_sequence);
        if(tick!=health.sequence[TD3_HEALTH_TICK]&&tick)
            motor_td3_health_progress(&health,TD3_HEALTH_TICK,now,tick);
        if(adc!=health.sequence[TD3_HEALTH_ADC]&&adc)
            motor_td3_health_progress(&health,TD3_HEALTH_ADC,now,adc);
        if(owner&&!health.link_armed) motor_td3_health_watch_link(&health,now);
        if(health.link_armed&&validated_stop_seq!=health.link_sequence)
            motor_td3_health_heartbeat_validated(&health,now,validated_stop_seq);
    }
    motor_td3_g431_wd_status.fault=health.fault;
    motor_td3_g431_wd_status.main_count=(uint32_t)main_sequence;
    motor_td3_g431_wd_status.tick_count=(uint32_t)tick;
    motor_td3_g431_wd_status.adc_count=adc;
    motor_td3_g431_wd_status.link_armed=health.link_armed;
    motor_td3_g431_wd_status.link_seq=(uint32_t)health.link_sequence;
    motor_td3_g431_wd_status.now_ms=(uint32_t)(now/1000U);
    motor_td3_g431_wd_status.irq_fault=board_fault;
    if(health.fault) { off();return 0; }
    if(motor_td3_health_may_feed(&health,now)) {
        IWDG->KR=0xAAAAU;
        ++motor_td3_g431_wd_status.feeds;
        motor_td3_g431_wd_status.last_feed_ms=(uint32_t)(now/1000U);
    }
    return 1;
}
int motor_td3_g431_wd_skip_adc(void) { return motor_td3_g431_wd_test_mode==1U; }
void motor_td3_g431_wd_test_point(void) {
    if(motor_td3_g431_wd_test_mode==3U) __disable_irq();
    if(motor_td3_g431_wd_test_mode==2U||motor_td3_g431_wd_test_mode==3U)
        while(1) { __NOP(); } /* IWDG, never ISR refresh, terminates this fault. */
}
