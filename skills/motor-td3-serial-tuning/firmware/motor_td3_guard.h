#ifndef MOTOR_TD3_GUARD_H
#define MOTOR_TD3_GUARD_H
#include <stdint.h>
/* Call from the control task. UART only decodes/enqueues; no direct PI writes.
 * Board must additionally implement hardware overcurrent, E-stop and PWM-off.
 * now_us is a monotonic uint64_t board timestamp, not a wrapping uint32_t tick. */
typedef struct {
    float kp_min,kp_max,ki_min,ki_max,kp_step,ki_step,kp_baseline,ki_baseline;
    float current_limit,speed_limit,vbus_min,vbus_max,temperature_limit;
    uint32_t lease_max_us,link_timeout_us,trial_max_us,command_max;
} motor_td3_limits;
typedef struct {
    motor_td3_limits limits;
    float kp,ki;
    uint64_t deadline_us,last_rx_us,started_us,last_tick_us,t_apply_us;
    uint32_t applied_seq,commands;
    int enabled,fault;
} motor_td3_guard;
enum { MOTOR_TD3_BAD_LIMIT=1, MOTOR_TD3_BAD_ACTION=2, MOTOR_TD3_BAD_SEQUENCE=3,
       MOTOR_TD3_OVERCURRENT=4, MOTOR_TD3_OVERSPEED=5, MOTOR_TD3_SENSOR=6,
       MOTOR_TD3_LEASE=7, MOTOR_TD3_LINK=8, MOTOR_TD3_TIME=9 };
int motor_td3_init(motor_td3_guard *,const motor_td3_limits *);
int motor_td3_begin(motor_td3_guard *,uint64_t now_us,uint32_t lease_us);
/* Atomic on control task boundary. Preserve/clamp integral-output state using
 * the board's independently verified bumpless PI implementation. */
int motor_td3_apply(motor_td3_guard *,uint64_t now_us,uint32_t seq,float kp,float ki,uint32_t lease_us);
void motor_td3_tick(motor_td3_guard *,uint64_t now_us,float current,float speed,float vbus,float temperature,int estop);
void motor_td3_stop(motor_td3_guard *);
/* No clear-fault API. Reset/rearm only by the board's operator procedure. */
#endif
