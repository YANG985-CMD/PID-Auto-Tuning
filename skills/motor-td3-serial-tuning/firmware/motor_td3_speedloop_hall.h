#ifndef MOTOR_TD3_SPEEDLOOP_HALL_H
#define MOTOR_TD3_SPEEDLOOP_HALL_H
#include <stdint.h>
typedef struct {
    uint64_t previous_us;
    uint32_t edges;
    uint8_t previous_code;
} motor_td3_speedloop_hall;
/* Vendor angle order 5,4,6,2,3,1; two pole pairs as in its rpm formula.
 * First edge has no known period. No clamping/filtering of high speed. */
int motor_td3_speedloop_hall_edge(motor_td3_speedloop_hall *,uint64_t now_us,
                                 uint8_t code,float *rpm,float *theta_step);
#endif
