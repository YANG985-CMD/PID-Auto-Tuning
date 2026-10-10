#ifndef MOTOR_TD3_G431_OFF_H
#define MOTOR_TD3_G431_OFF_H
#include "stm32g431xx.h"
/* Shared by the actual HAL adapter and RAM test. CH4 is an ADC trigger only.
 * Never set MOE, phase enable bits, or a GPIO mode here. */
#define TD3_G431_PHASE_MASK (TIM_CCER_CC1E|TIM_CCER_CC1NE|TIM_CCER_CC2E|TIM_CCER_CC2NE|TIM_CCER_CC3E|TIM_CCER_CC3NE)
static inline void motor_td3_g431_outputs_off(void) {
    if(RCC->APB2ENR & RCC_APB2ENR_TIM1EN) {
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        TIM1->CCER &= ~TD3_G431_PHASE_MASK;
        __DSB();
    }
}
static inline int motor_td3_g431_outputs_enabled(void) {
    return (RCC->APB2ENR & RCC_APB2ENR_TIM1EN) &&
        (TIM1->BDTR & TIM_BDTR_MOE) && (TIM1->CCER & TD3_G431_PHASE_MASK);
}
#endif
