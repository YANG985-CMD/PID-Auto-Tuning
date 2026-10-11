#include "motor_td3_guard.h"
#include <math.h>
#include <string.h>

static int trip(motor_td3_guard *g,int fault) { g->enabled=0; if(!g->fault) g->fault=fault; return 0; }
static int bounds(float lo,float hi,float baseline,float step) {
    return isfinite(lo)&&isfinite(hi)&&isfinite(baseline)&&isfinite(step)&&
        lo>=0&&hi>lo&&baseline>=lo&&baseline<=hi&&step>0&&step<=hi-lo;
}
int motor_td3_init(motor_td3_guard *g,const motor_td3_limits *l) {
    if(!g||!l) return 0;
    memset(g,0,sizeof(*g)); g->limits=*l;
    if(!bounds(l->kp_min,l->kp_max,l->kp_baseline,l->kp_step)||
       !bounds(l->ki_min,l->ki_max,l->ki_baseline,l->ki_step)||
       !isfinite(l->current_limit)||l->current_limit<=0||
       !isfinite(l->speed_limit)||l->speed_limit<=0||
       !isfinite(l->vbus_min)||!isfinite(l->vbus_max)||l->vbus_min<=0||l->vbus_min>=l->vbus_max||
       !isfinite(l->temperature_limit)||!l->lease_max_us||!l->link_timeout_us||!l->trial_max_us||!l->command_max)
        return trip(g,MOTOR_TD3_BAD_LIMIT);
    g->kp=l->kp_baseline; g->ki=l->ki_baseline; return 1;
}
int motor_td3_begin(motor_td3_guard *g,uint64_t now,uint32_t lease) {
    if(!g||g->fault||g->enabled) return 0;
    if(!lease||lease>g->limits.lease_max_us||now<g->last_tick_us) return trip(g,MOTOR_TD3_BAD_ACTION);
    g->kp=g->limits.kp_baseline; g->ki=g->limits.ki_baseline;
    g->started_us=g->last_rx_us=g->last_tick_us=now; g->deadline_us=now+lease;
    g->commands=0; g->enabled=1; return 1;
}
int motor_td3_apply(motor_td3_guard *g,uint64_t now,uint32_t seq,float kp,float ki,uint32_t lease) {
    if(!g||g->fault||!g->enabled) return 0;
    if(now<g->last_tick_us||now>=g->deadline_us||now-g->last_rx_us>=g->limits.link_timeout_us||
       now-g->started_us>=g->limits.trial_max_us) return trip(g,MOTOR_TD3_TIME);
    if(!seq||seq<=g->applied_seq) return trip(g,MOTOR_TD3_BAD_SEQUENCE);
    if(!isfinite(kp)||!isfinite(ki)||kp<g->limits.kp_min||kp>g->limits.kp_max||
       ki<g->limits.ki_min||ki>g->limits.ki_max||
       fabsf(kp-g->kp)>g->limits.kp_step+1e-9f||fabsf(ki-g->ki)>g->limits.ki_step+1e-9f||
       !lease||lease>g->limits.lease_max_us||g->commands>=g->limits.command_max)
        return trip(g,MOTOR_TD3_BAD_ACTION);
    g->kp=kp; g->ki=ki; g->applied_seq=seq; g->t_apply_us=now;
    g->last_rx_us=now; g->deadline_us=now+lease; g->commands++; return 1;
}
void motor_td3_tick(motor_td3_guard *g,uint64_t now,float current,float speed,float vbus,float temperature,int estop) {
    int thermal_enabled;
    if(!g) return;
    if(now<g->last_tick_us) { trip(g,MOTOR_TD3_TIME); return; }
    g->last_tick_us=now;
    if(!g->enabled) return;
    /* A negative temperature limit explicitly means that this board has no
     * temperature channel. The live profile still keeps voltage, Hall/speed,
     * lease, link, software current and hardware comparator protection. */
    thermal_enabled=g->limits.temperature_limit>=0.0f;
    if(estop||!isfinite(current)||!isfinite(speed)||!isfinite(vbus)||
       (thermal_enabled&&(!isfinite(temperature)||temperature>=g->limits.temperature_limit))||
       vbus<g->limits.vbus_min||vbus>g->limits.vbus_max)
        trip(g,MOTOR_TD3_SENSOR);
    else if(fabsf(current)>=g->limits.current_limit) trip(g,MOTOR_TD3_OVERCURRENT);
    else if(fabsf(speed)>=g->limits.speed_limit) trip(g,MOTOR_TD3_OVERSPEED);
    else if(now>=g->deadline_us) trip(g,MOTOR_TD3_LEASE);
    else if(now-g->last_rx_us>=g->limits.link_timeout_us) trip(g,MOTOR_TD3_LINK);
    else if(now-g->started_us>=g->limits.trial_max_us) trip(g,MOTOR_TD3_TIME);
}
void motor_td3_stop(motor_td3_guard *g) { if(g) g->enabled=0; }
