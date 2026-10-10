#ifndef MOTOR_TD3_HEALTH_H
#define MOTOR_TD3_HEALTH_H
#include <stdint.h>
/* Watchdog refresh permission only. This never authorizes PWM or motor restart.
 * Call the refresh decision in foreground; never refresh from an ISR.
 * Limits must come from the target's timing analysis before motor use. */
enum { TD3_HEALTH_MAIN=0, TD3_HEALTH_TICK=1, TD3_HEALTH_ADC=2 };
enum { TD3_HEALTH_CONFIG=1, TD3_HEALTH_TIME=2, TD3_HEALTH_SEQUENCE=3,
       TD3_HEALTH_MAIN_STALE=4, TD3_HEALTH_TICK_STALE=5,
       TD3_HEALTH_ADC_STALE=6, TD3_HEALTH_LINK_STALE=7, TD3_HEALTH_BOARD=8 };
typedef struct {
    uint32_t main_us,tick_us,adc_us,link_us;
} motor_td3_health_limits;
typedef struct {
    motor_td3_health_limits limits;
    uint64_t last_now,seen[3],sequence[3],fed_sequence[3],link_seen,link_sequence;
    unsigned valid,link_armed,fault;
} motor_td3_health;
int motor_td3_health_init(motor_td3_health *,const motor_td3_health_limits *,uint64_t now);
int motor_td3_health_progress(motor_td3_health *,unsigned kind,uint64_t now,uint64_t sequence);
int motor_td3_health_watch_link(motor_td3_health *,uint64_t now);
/* Only after protocol identity/session/CRC validation. Reject duplicates and
 * late arrivals; a received frame must never revive an expired session. */
int motor_td3_health_heartbeat_validated(motor_td3_health *,uint64_t now,uint64_t sequence);
int motor_td3_health_check(motor_td3_health *,uint64_t now);
int motor_td3_health_may_feed(motor_td3_health *,uint64_t now);
void motor_td3_health_board_fault(motor_td3_health *);
#endif
