#ifndef MOTOR_TD3_SPEEDLOOP_BASELINE_H
#define MOTOR_TD3_SPEEDLOOP_BASELINE_H
#include <stdint.h>
/* A single operator-started reproduction of the known-running example.
 * This endpoint has no gain, remote start, Actor, or learning commands. */
typedef struct {
    uint32_t magic, state, fault, samples, hall_edges, started_ms, elapsed_ms;
    uint32_t feeds, reset_flags, host_sequence, last_host_ms, last_adc_ms;
    uint32_t phase_enabled, stage, rejected_starts;
    float speed_rpm, ia, ib, ic, bus_v, peak_nominal_a, kp, ki;
} motor_td3_baseline_record;
extern volatile motor_td3_baseline_record motor_td3_baseline_status;
extern const char motor_td3_baseline_build_id[];
void motor_td3_baseline_off(void);
void motor_td3_baseline_fault(uint32_t reason);
int motor_td3_baseline_boot(void);
void motor_td3_baseline_init(void);
void motor_td3_baseline_can_init(void);
void motor_td3_baseline_button(void);
void motor_td3_baseline_tick(void);
void motor_td3_baseline_adc(void);
void motor_td3_baseline_after_step(void);
int motor_td3_baseline_hall(uint32_t period, uint32_t code);
void motor_td3_baseline_poll(void);
void motor_td3_baseline_bus_updated(void);
#endif
