#ifndef MOTOR_TD3_SPEEDLOOP_PI_BIND_H
#define MOTOR_TD3_SPEEDLOOP_PI_BIND_H
#include "motor_td3_speedloop_pi.h"
extern motor_td3_speedloop_pi motor_td3_speedloop_pi_state;
void motor_td3_speedloop_pi_bind_init(void);
/* Disable outputs, clear the software start flags and latch the first fault. */
void motor_td3_speedloop_pi_stop(void);
void motor_td3_speedloop_pi_fast(float error);
int motor_td3_speedloop_pi_model_boundary(float error,int reset,float *integral);
/* Queue from a future validated transport/guard. This is not a CAN command handler. */
int motor_td3_speedloop_pi_queue(unsigned mode,uint32_t sequence,float kp,float ki,uint64_t deadline_us);
#ifdef MOTOR_TD3_SPEEDLOOP_PI_HOST
uint64_t motor_td3_speedloop_pi_host_time_us(void);
#endif
#endif
