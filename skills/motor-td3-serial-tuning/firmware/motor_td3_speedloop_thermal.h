#ifndef MOTOR_TD3_SPEEDLOOP_THERMAL_H
#define MOTOR_TD3_SPEEDLOOP_THERMAL_H
#include "motor_td3_thermal_feed.h"
/* LOCKED integration audit. No calibrated current, verified thermal limits or
 * known boot seed is supplied. It must remain motion inhibited. The 100 Hz
 * sequential software ADC path is not production FOC/RMS sampling evidence. */
extern motor_td3_thermal_feed motor_td3_speedloop_thermal_state;
void motor_td3_speedloop_thermal_init(void);
void motor_td3_speedloop_thermal_tick_1ms(void); /* clock only, no float/guard work */
void motor_td3_speedloop_thermal_poll(void);
void motor_td3_speedloop_thermal_sample(void);
#endif
