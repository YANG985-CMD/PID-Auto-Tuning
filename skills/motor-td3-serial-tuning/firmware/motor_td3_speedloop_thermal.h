#ifndef MOTOR_TD3_SPEEDLOOP_THERMAL_H
#define MOTOR_TD3_SPEEDLOOP_THERMAL_H
#include "motor_td3_thermal_feed.h"
#include "motor_td3_thermal_can.h"
/* LOCKED integration audit. No calibrated current, verified thermal limits or
 * known boot seed is supplied. It must remain motion inhibited. The 100 Hz
 * sequential software ADC path is not production FOC/RMS sampling evidence. */
extern motor_td3_thermal_feed motor_td3_speedloop_thermal_state;
void motor_td3_speedloop_thermal_init(void);
void motor_td3_speedloop_thermal_tick_1ms(void); /* clock only, no float/guard work */
void motor_td3_speedloop_thermal_poll(void);
void motor_td3_speedloop_thermal_sample(void);
int motor_td3_speedloop_thermal_packet(uint8_t out[TD3_THERMAL_CAN_BYTES],
    uint64_t nonce,uint64_t boot,uint32_t snapshot_seq);
#endif
