#include "motor_td3_trial_timing.h"
#include <string.h>

static int trip(motor_td3_trial_timing *s, unsigned fault) {
    if(!s->fault) s->fault=fault;
    return 0;
}
int motor_td3_trial_timing_begin(motor_td3_trial_timing *s, uint64_t now) {
    if(!s || s->started) return 0; /* No rearm after STOP or failure. */
    memset(s,0,sizeof(*s));s->started=1;s->started_us=s->last_us=now;
    return 1;
}
int motor_td3_trial_timing_tick(motor_td3_trial_timing *s, uint64_t now, unsigned stage) {
    if(!s || !s->started || s->fault) return 0;
    if(now<s->last_us) return trip(s,TD3_TIMING_CLOCK);
    s->last_us=now;
    if(now-s->started_us>=TD3_REVIEW_TOTAL_US) return trip(s,TD3_TIMING_TOTAL);
    /* Stage 4 comes from the generated model, not elapsed-time inference. */
    if(!s->run_seen) {
        if(now-s->started_us>=TD3_REVIEW_STARTUP_US) return trip(s,TD3_TIMING_STARTUP);
        if(stage==4) {s->run_seen=1;s->run_started_us=now;}
    } else {
        if(stage!=4) return trip(s,TD3_TIMING_REGRESSION);
        if(now-s->run_started_us>=TD3_REVIEW_CLOSED_US) return trip(s,TD3_TIMING_CLOSED);
    }
    return 1;
}
