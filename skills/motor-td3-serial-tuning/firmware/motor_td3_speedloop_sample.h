#ifndef MOTOR_TD3_SPEEDLOOP_SAMPLE_H
#define MOTOR_TD3_SPEEDLOOP_SAMPLE_H
#include <stdint.h>
/* Diagnostic only: nominal 100 Hz, sequential ADCs, no FOC synchronization. */
extern volatile uint32_t motor_td3_speedloop_sample_count;
extern volatile uint32_t motor_td3_speedloop_sample_errors;
void motor_td3_speedloop_sample(void);
#endif
