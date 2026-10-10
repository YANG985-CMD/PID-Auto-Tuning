#include "motor_td3_thermal.h"
#include <float.h>
#include <math.h>
#include <string.h>

static int trip(motor_td3_thermal *g, unsigned fault) {
    if(!g->fault) g->fault=fault;
    if(g->disable) g->disable(g->user);
    return 0;
}
static int positive(float v) { return isfinite(v)&&v>0.0f; }
void motor_td3_thermal_window_init(motor_td3_thermal_window *w) {
    if(w) memset(w,0,sizeof(*w));
}
int motor_td3_thermal_window_add(motor_td3_thermal_window *w,const float a[3],unsigned valid) {
    unsigned p;float sum[3],peak[3];
    if(!w) return 0;
    if(w->invalid||!a||valid!=1||w->samples==UINT32_MAX) { w->invalid=1;return 0; }
    for(p=0;p<3;++p) {
        if(!isfinite(a[p])) { w->invalid=1;return 0; }
        sum[p]=w->sum_a2[p]+a[p]*a[p];
        peak[p]=fmaxf(w->peak_abs_a[p],fabsf(a[p]));
        if(!isfinite(sum[p])) { w->invalid=1;return 0; }
    }
    for(p=0;p<3;++p) { w->sum_a2[p]=sum[p];w->peak_abs_a[p]=peak[p]; }
    ++w->samples;return 1;
}
int motor_td3_thermal_window_finish(const motor_td3_thermal_window *w,motor_td3_thermal_observation *o) {
    unsigned p;
    if(!o) return 0;
    o->valid=0;
    if(!w||w->invalid||!w->samples) return 0;
    for(p=0;p<3;++p) {
        o->mean_square_a2[p]=w->sum_a2[p]/(float)w->samples;
        o->peak_abs_a[p]=w->peak_abs_a[p];
    }
    o->samples=w->samples;o->valid=1;return 1;
}
int motor_td3_thermal_init(motor_td3_thermal *g,const motor_td3_thermal_limits *l,
    const motor_td3_thermal_seed *seed,uint64_t now,void (*disable)(void *),void *user) {
    unsigned p;
    if(!g) return 0;
    memset(g,0,sizeof(*g));g->disable=disable;g->user=user;
    if(disable) disable(user); /* initial hardware state is always off */
    g->last_end_us=g->last_now_us=now;
    if(!l||!disable) return trip(g,TD3_THERMAL_CONFIG);
    g->limits=*l;
    if(l->validated!=1||!l->window_us||!l->window_samples||l->window_us%l->window_samples||
       !l->max_energized_us||!l->max_stalled_us||l->max_stalled_us>l->max_energized_us||
       l->window_us>l->max_stalled_us||!positive(l->stall_speed_rpm)||!positive(l->stall_rms_a)||
       !isfinite(l->stall_rms_a*l->stall_rms_a)) return trip(g,TD3_THERMAL_CONFIG);
    for(p=0;p<3;++p) {
        if(!positive(l->continuous_rms_a[p])||!positive(l->instantaneous_trip_a[p])||
           !positive(l->budget_a2s[p])||l->instantaneous_trip_a[p]<=l->continuous_rms_a[p]||
           l->stall_rms_a>=l->instantaneous_trip_a[p]||
           !isfinite(l->instantaneous_trip_a[p]*l->instantaneous_trip_a[p]))
            return trip(g,TD3_THERMAL_CONFIG);
    }
    g->configured=1;
    if(!seed||seed->known!=1) return trip(g,TD3_THERMAL_BOOT_UNKNOWN);
    for(p=0;p<3;++p) {
        if(!isfinite(seed->used_a2s[p])||seed->used_a2s[p]<0.0f)
            return trip(g,TD3_THERMAL_BOOT_UNKNOWN);
        g->used_a2s[p]=seed->used_a2s[p];
    }
    g->energized_us=seed->energized_us;g->stalled_us=seed->stalled_us;
    if(g->stalled_us>g->energized_us) return trip(g,TD3_THERMAL_BOOT_UNKNOWN);
    for(p=0;p<3;++p) if(g->used_a2s[p]>=l->budget_a2s[p]) return trip(g,TD3_THERMAL_BUDGET);
    if(g->energized_us>=l->max_energized_us) return trip(g,TD3_THERMAL_DURATION);
    if(g->stalled_us>=l->max_stalled_us) return trip(g,TD3_THERMAL_STALL);
    return 1;
}
int motor_td3_thermal_check(motor_td3_thermal *g,uint64_t now) {
    uint64_t age;
    if(!g) return 0;
    if(g->fault) return trip(g,g->fault);
    if(!g->configured) return trip(g,TD3_THERMAL_CONFIG);
    if(now<g->last_now_us) return trip(g,TD3_THERMAL_TIME);
    g->last_now_us=now;age=now-g->last_end_us;
    /* Equality allows the observer/checker order at the window deadline. */
    if(age>(uint64_t)g->limits.window_us+g->limits.max_age_us) return trip(g,TD3_THERMAL_STALE);
    return 1;
}
int motor_td3_thermal_observe(motor_td3_thermal *g,const motor_td3_thermal_observation *o,uint64_t now) {
    unsigned p,stalled=0;double next[3],dt;
    if(!motor_td3_thermal_check(g,now)) return 0;
    if(!o||o->valid!=1||o->output_active>1||!isfinite(o->min_abs_speed_rpm)||o->min_abs_speed_rpm<0.0f)
        return trip(g,TD3_THERMAL_SENSOR);
    if(g->sequence==UINT64_MAX||o->seq!=g->sequence+1) return trip(g,TD3_THERMAL_SEQUENCE);
    if(o->end_us<=g->last_end_us||o->end_us>now||o->end_us-g->last_end_us!=g->limits.window_us||
       now-o->end_us>g->limits.max_age_us) return trip(g,TD3_THERMAL_TIME);
    if(o->samples!=g->limits.window_samples) return trip(g,TD3_THERMAL_SENSOR);
    dt=(double)g->limits.window_us/1000000.0;
    for(p=0;p<3;++p) {
        float square=o->mean_square_a2[p],peak=o->peak_abs_a[p];double delta;
        if(!isfinite(square)||square<0.0f||!isfinite(peak)||peak<0.0f||
           !isfinite(peak*peak)||
           (square>peak*peak&&square/(peak*peak)>1.0f+16.0f*FLT_EPSILON))
            return trip(g,TD3_THERMAL_SENSOR);
        if(peak>=g->limits.instantaneous_trip_a[p]) return trip(g,TD3_THERMAL_CURRENT);
        /* Conservative excess-load budget: no unvalidated cooling credit. */
        delta=fmax(0.0,(double)square-(double)g->limits.continuous_rms_a[p]*g->limits.continuous_rms_a[p])*dt;
        next[p]=g->used_a2s[p]+delta;
        if(!isfinite(next[p])) return trip(g,TD3_THERMAL_SENSOR);
        if(square>=g->limits.stall_rms_a*g->limits.stall_rms_a) stalled=1;
    }
    g->sequence=o->seq;g->last_end_us=o->end_us;g->has_window=1;
    for(p=0;p<3;++p) g->used_a2s[p]=fmin(next[p],g->limits.budget_a2s[p]);
    for(p=0;p<3;++p) if(next[p]>=g->limits.budget_a2s[p]) return trip(g,TD3_THERMAL_BUDGET);
    if(o->output_active) {
        if(g->limits.window_us>=g->limits.max_energized_us-g->energized_us) {
            g->energized_us=g->limits.max_energized_us;return trip(g,TD3_THERMAL_DURATION);
        }
        g->energized_us+=g->limits.window_us;
        if(stalled&&o->min_abs_speed_rpm<=g->limits.stall_speed_rpm) {
            if(g->limits.window_us>=g->limits.max_stalled_us-g->stalled_us) {
                g->stalled_us=g->limits.max_stalled_us;return trip(g,TD3_THERMAL_STALL);
            }
            g->stalled_us+=g->limits.window_us;
        }
    }
    return 1;
}
int motor_td3_thermal_may_start(motor_td3_thermal *g,uint64_t now) {
    return motor_td3_thermal_check(g,now)&&g->has_window;
}
float motor_td3_thermal_load(const motor_td3_thermal *g) {
    unsigned p;float load=0.0f;
    if(!g||!g->configured||g->fault==TD3_THERMAL_BOOT_UNKNOWN) return NAN;
    for(p=0;p<3;++p) load=fmaxf(load,g->used_a2s[p]/g->limits.budget_a2s[p]);
    return load;
}
