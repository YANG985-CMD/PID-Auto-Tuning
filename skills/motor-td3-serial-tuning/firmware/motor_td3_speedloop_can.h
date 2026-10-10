#ifndef MOTOR_TD3_SPEEDLOOP_CAN_H
#define MOTOR_TD3_SPEEDLOOP_CAN_H
#include "motor_td3_can_control.h"
typedef struct {
    motor_td3_can_control *endpoint;
    motor_td3_can_hooks board;
    uint64_t now_us;
    float error,previous_error,*integral;
    int in_boundary,applied,reset,estop;
} motor_td3_speedloop_can;
/* Install before control_init uses the returned hooks. Board begin may set the
 * reference and physically enable outputs, but must NOT write PI gains. It is
 * reached only after guard checks and an actual bumpless PI commit. No limits
 * or motion capabilities are created/changed by this adapter. */
int motor_td3_speedloop_can_attach(motor_td3_speedloop_can *,motor_td3_can_control *,
                                  const motor_td3_can_hooks *board,motor_td3_can_hooks *out);
#endif
