#ifndef MOTOR_TD3_G431_ADAPTER_H
#define MOTOR_TD3_G431_ADAPTER_H
#include <stdint.h>
/* This build is permanently motion inhibited. There is no arming API or flag.
 * debugger_boot_token is a one-use diagnostic identity, provisioned AFTER reset
 * with the core halted. It is NOT a production boot-identity implementation. */
extern volatile uint64_t motor_td3_g431_debugger_boot_token;
void motor_td3_g431_disable(void);
void motor_td3_g431_init(void);
void motor_td3_g431_tick_1ms(void);
void motor_td3_g431_poll(void);
void motor_td3_g431_adc_sample(void);
int motor_td3_g431_hall_capture(uint32_t period_ticks,uint8_t hall_code);
void motor_td3_g431_button_stop(void);
void motor_td3_g431_fault_irq(void);
#endif
