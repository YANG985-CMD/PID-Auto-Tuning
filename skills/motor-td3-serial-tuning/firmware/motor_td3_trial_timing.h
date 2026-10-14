#ifndef MOTOR_TD3_TRIAL_TIMING_H
#define MOTOR_TD3_TRIAL_TIMING_H
#include <stdint.h>

/* Single baseline review only. These are experiment limits, not thermal limits. */
#define TD3_REVIEW_TOTAL_US 5000000ULL
#define TD3_REVIEW_STARTUP_US 2600000ULL
#define TD3_REVIEW_CLOSED_US 2800000ULL
typedef struct {
    uint64_t started_us, run_started_us, last_us;
    uint32_t started, run_seen, fault;
} motor_td3_trial_timing;
enum { TD3_TIMING_CLOCK=1, TD3_TIMING_TOTAL=2, TD3_TIMING_STARTUP=3,
       TD3_TIMING_REGRESSION=4, TD3_TIMING_CLOSED=5 };
int motor_td3_trial_timing_begin(motor_td3_trial_timing *s, uint64_t now);
int motor_td3_trial_timing_tick(motor_td3_trial_timing *s, uint64_t now, unsigned stage);
#endif
