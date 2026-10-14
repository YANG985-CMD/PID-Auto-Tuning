#ifndef MOTOR_TD3_STARTUP_HANDOVER_H
#define MOTOR_TD3_STARTUP_HANDOVER_H
#include <stdint.h>
typedef struct {
    float last_open_angle,initial_offset,selected_angle;
    uint32_t closed_steps;
    uint8_t open_seen,closed_seen;
} motor_td3_startup_handover;
extern motor_td3_startup_handover motor_td3_startup_handover_state;
void motor_td3_startup_handover_reset(void);
float motor_td3_startup_handover_angle(unsigned stage,float selected_angle,float hall_angle);
int motor_td3_startup_handover_pi(unsigned stage,int reset,float error,float kp,
                                 float previous_iq,float *integral);
#endif
