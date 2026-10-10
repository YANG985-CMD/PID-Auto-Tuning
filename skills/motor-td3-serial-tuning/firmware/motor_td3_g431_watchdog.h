#ifndef MOTOR_TD3_G431_WATCHDOG_H
#define MOTOR_TD3_G431_WATCHDOG_H
#include <stdint.h>
/* For the motion-inhibited SpeedLoop diagnostic only. No arming API. */
typedef struct {
    uint32_t magic,active,fault,feeds,main_count,tick_count,adc_count;
    uint32_t link_armed,link_seq,last_feed_ms,now_ms,reset_flags,boot_latched,irq_fault;
} motor_td3_g431_wd_record;
extern volatile motor_td3_g431_wd_record motor_td3_g431_wd_status;
/* Debugger-only failure injection: 0 normal, 1 skip ADC, 2 stall foreground,
 * 3 stall with maskable IRQs disabled. Never exposed through CAN. */
extern volatile uint32_t motor_td3_g431_wd_test_mode;
int motor_td3_g431_wd_boot_check(void);
int motor_td3_g431_wd_init(uint64_t now);
int motor_td3_g431_wd_service(uint64_t now,uint32_t adc,unsigned owner,
                             uint32_t validated_stop_seq,unsigned board_fault);
int motor_td3_g431_wd_skip_adc(void);
void motor_td3_g431_wd_test_point(void);
#endif
