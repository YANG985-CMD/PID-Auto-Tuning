#include "motor_td3_health.h"
#include <string.h>
static int fail(motor_td3_health *s,unsigned reason) {
    if(s&&!s->fault) s->fault=reason;
    return 0;
}
static int clock_ok(motor_td3_health *s,uint64_t now) {
    if(!s||s->fault) return 0;
    if(now<s->last_now) return fail(s,TD3_HEALTH_TIME);
    s->last_now=now;return 1;
}
int motor_td3_health_init(motor_td3_health *s,const motor_td3_health_limits *l,uint64_t now) {
    if(!s||!l) return 0;
    memset(s,0,sizeof(*s));s->limits=*l;s->last_now=now;
    s->seen[0]=s->seen[1]=s->seen[2]=s->link_seen=now;
    if(!l->main_us||!l->tick_us||!l->adc_us||!l->link_us) return fail(s,TD3_HEALTH_CONFIG);
    return 1;
}
int motor_td3_health_check(motor_td3_health *s,uint64_t now) {
    if(!clock_ok(s,now)) return 0;
    if(now-s->seen[0]>=s->limits.main_us) return fail(s,TD3_HEALTH_MAIN_STALE);
    if(now-s->seen[1]>=s->limits.tick_us) return fail(s,TD3_HEALTH_TICK_STALE);
    if(now-s->seen[2]>=s->limits.adc_us) return fail(s,TD3_HEALTH_ADC_STALE);
    if(s->link_armed&&now-s->link_seen>=s->limits.link_us) return fail(s,TD3_HEALTH_LINK_STALE);
    return 1;
}
int motor_td3_health_progress(motor_td3_health *s,unsigned kind,uint64_t now,uint64_t sequence) {
    if(!motor_td3_health_check(s,now)) return 0;
    if(kind>2||!sequence||sequence<=s->sequence[kind]) return fail(s,TD3_HEALTH_SEQUENCE);
    s->seen[kind]=now;s->sequence[kind]=sequence;s->valid|=1U<<kind;return 1;
}
int motor_td3_health_watch_link(motor_td3_health *s,uint64_t now) {
    if(!motor_td3_health_check(s,now)) return 0;
    if(s->link_armed) return fail(s,TD3_HEALTH_SEQUENCE);
    s->link_armed=1;s->link_seen=now;return 1;
}
int motor_td3_health_heartbeat_validated(motor_td3_health *s,uint64_t now,uint64_t sequence) {
    if(!motor_td3_health_check(s,now)) return 0;
    if(!s->link_armed||!sequence||s->link_sequence==UINT64_MAX||sequence!=s->link_sequence+1)
        return fail(s,TD3_HEALTH_SEQUENCE);
    s->link_seen=now;s->link_sequence=sequence;return 1;
}
int motor_td3_health_may_feed(motor_td3_health *s,uint64_t now) {
    unsigned i;
    if(!motor_td3_health_check(s,now)||s->valid!=7U) return 0;
    for(i=0;i<3;i++) if(s->sequence[i]==s->fed_sequence[i]) return 0;
    for(i=0;i<3;i++) s->fed_sequence[i]=s->sequence[i];
    return 1;
}
void motor_td3_health_board_fault(motor_td3_health *s) { (void)fail(s,TD3_HEALTH_BOARD); }
