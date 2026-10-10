#include "motor_td3_health.h"
#include <assert.h>
#include <stdio.h>
static motor_td3_health state;
static motor_td3_health_limits limits={5000,5000,30000,200000};
static void init(void) { assert(motor_td3_health_init(&state,&limits,0)); }
static void progress(uint64_t now,uint64_t sequence) {
    assert(motor_td3_health_progress(&state,TD3_HEALTH_MAIN,now,sequence));
    assert(motor_td3_health_progress(&state,TD3_HEALTH_TICK,now,sequence));
    assert(motor_td3_health_progress(&state,TD3_HEALTH_ADC,now,sequence));
}
int main(void) {
    unsigned i,cases=0;
    init();assert(!motor_td3_health_may_feed(&state,0));cases++;
    progress(1000,1);assert(motor_td3_health_may_feed(&state,1000));cases++;
    assert(!motor_td3_health_may_feed(&state,1001));cases++;
    assert(motor_td3_health_progress(&state,TD3_HEALTH_TICK,2000,2));
    assert(!motor_td3_health_may_feed(&state,2000));cases++;
    assert(!motor_td3_health_check(&state,6000));assert(state.fault==TD3_HEALTH_MAIN_STALE);cases++;
    assert(!motor_td3_health_progress(&state,TD3_HEALTH_MAIN,6000,2));cases++;
    init();progress(1000,1);
    assert(motor_td3_health_progress(&state,TD3_HEALTH_MAIN,4000,2));
    assert(!motor_td3_health_check(&state,6000));assert(state.fault==TD3_HEALTH_TICK_STALE);cases++;
    init();progress(1000,1);
    for(i=2;i<=30;i++) {
        assert(motor_td3_health_progress(&state,TD3_HEALTH_MAIN,i*1000,i));
        assert(motor_td3_health_progress(&state,TD3_HEALTH_TICK,i*1000,i));
    }
    assert(!motor_td3_health_check(&state,31000));assert(state.fault==TD3_HEALTH_ADC_STALE);cases++;
    init();progress(1000,1);assert(!motor_td3_health_progress(&state,0,1000,1));
    assert(state.fault==TD3_HEALTH_SEQUENCE);cases++;
    init();progress(1000,1);assert(!motor_td3_health_check(&state,999));cases++;
    init();progress(1000,1);assert(motor_td3_health_watch_link(&state,1000));
    assert(motor_td3_health_heartbeat_validated(&state,1000,1));
    assert(!motor_td3_health_heartbeat_validated(&state,1000,1));cases++;
    init();progress(1000,1);assert(motor_td3_health_watch_link(&state,1000));
    for(i=2;i<=200;i++) progress(i*1000,i);
    assert(!motor_td3_health_heartbeat_validated(&state,201000,1));
    assert(state.fault==TD3_HEALTH_LINK_STALE);cases++;
    assert(!motor_td3_health_watch_link(&state,201000));cases++;
    init();progress(1000,1);motor_td3_health_board_fault(&state);
    assert(!motor_td3_health_may_feed(&state,1000));assert(state.fault==TD3_HEALTH_BOARD);cases++;
    limits.tick_us=0;assert(!motor_td3_health_init(&state,&limits,0));cases++;
    printf("{\"software_only\":true,\"checks_passed\":%u}\n",cases);
    return 0;
}
