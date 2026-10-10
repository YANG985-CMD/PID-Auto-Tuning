#include "motor_td3_thermal_feed.h"
#include <float.h>
#include <math.h>

static int fail(motor_td3_thermal_feed *f,unsigned reason) {
    if(!f->fault) f->fault=reason;
    /* Also invalidate the contained guard so a caller cannot bypass a feed
     * fault by accidentally consulting only the completed-window permission. */
    if(!f->guard.fault) {
        switch(f->fault) {
        case TD3_FEED_SEQUENCE:f->guard.fault=TD3_THERMAL_SEQUENCE;break;
        case TD3_FEED_TIME:f->guard.fault=TD3_THERMAL_TIME;break;
        case TD3_FEED_STALE:f->guard.fault=TD3_THERMAL_STALE;break;
        case TD3_FEED_PEAK:f->guard.fault=TD3_THERMAL_CURRENT;break;
        case TD3_FEED_ADC:f->guard.fault=TD3_THERMAL_SENSOR;break;
        default:f->guard.fault=TD3_THERMAL_CONFIG;break;
        }
    }
    if(f->disable) f->disable(f->user);
    return 0;
}
int motor_td3_thermal_feed_init(motor_td3_thermal_feed *f,
    const motor_td3_current_calibration *c,const motor_td3_thermal_limits *l,
    const motor_td3_thermal_seed *seed,uint64_t now,void (*disable)(void *),void *user) {
    unsigned p;
    if(!f) { if(disable) disable(user);return 0; }
    /* Repeated init must not erase a fault or cumulative warm-state budget. */
    if(f->initialized) return fail(f,TD3_FEED_INIT);
    f->initialized=1;f->disable=disable;f->user=user;
    if(disable) disable(user);
    if(!disable) return fail(f,TD3_FEED_INIT);
    if(!c||c->calibrated!=1) return fail(f,TD3_FEED_CALIBRATION);
    for(p=0;p<3;++p) {
        if(!isfinite(c->zero_adc[p])||!isfinite(c->gain_a_per_count[p])||c->gain_a_per_count[p]<=0||
           c->verified_low_adc[p]<1||c->verified_high_adc[p]>4094||
           c->zero_adc[p]<=c->verified_low_adc[p]||c->zero_adc[p]>=c->verified_high_adc[p])
            return fail(f,TD3_FEED_CALIBRATION);
    }
    f->calibration=*c;
    if(!motor_td3_thermal_init(&f->guard,l,seed,now,disable,user)) return fail(f,TD3_FEED_THERMAL);
    f->period_us=l->window_us/l->window_samples;
    f->last_capture_us=f->last_now_us=now;f->min_abs_speed_rpm=FLT_MAX;
    motor_td3_thermal_window_init(&f->window);
    return 1;
}
int motor_td3_thermal_feed_check(motor_td3_thermal_feed *f,uint64_t now) {
    uint64_t age;
    if(!f) return 0;
    if(f->fault) return fail(f,f->fault);
    if(!f->initialized||!f->period_us) return fail(f,TD3_FEED_INIT);
    if(now<f->last_now_us||now<f->last_capture_us) return fail(f,TD3_FEED_TIME);
    f->last_now_us=now;age=now-f->last_capture_us;
    if(age>(uint64_t)f->period_us+f->guard.limits.max_age_us) return fail(f,TD3_FEED_STALE);
    if(!motor_td3_thermal_check(&f->guard,now)) return fail(f,TD3_FEED_THERMAL);
    return 1;
}
int motor_td3_thermal_feed_sample(motor_td3_thermal_feed *f,const motor_td3_thermal_sample *s,uint64_t now) {
    unsigned p;float current[3];motor_td3_thermal_observation o={0};
    if(!motor_td3_thermal_feed_check(f,now)) return 0;
    if(!s||s->valid!=1||s->output_active>1||!isfinite(s->speed_rpm)) return fail(f,TD3_FEED_ADC);
    if(f->sample_sequence==UINT64_MAX||s->sequence!=f->sample_sequence+1) return fail(f,TD3_FEED_SEQUENCE);
    if(f->last_capture_us>UINT64_MAX-f->period_us||s->capture_us!=f->last_capture_us+f->period_us||
       s->capture_us>now||now-s->capture_us>f->guard.limits.max_age_us) return fail(f,TD3_FEED_TIME);
    for(p=0;p<3;++p) {
        /* Validity requires both the ADC rails and the measured calibration domain. */
        if(s->raw_adc[p]<f->calibration.verified_low_adc[p]||s->raw_adc[p]>f->calibration.verified_high_adc[p])
            return fail(f,TD3_FEED_ADC);
        current[p]=((float)s->raw_adc[p]-f->calibration.zero_adc[p])*f->calibration.gain_a_per_count[p];
        if(!isfinite(current[p])) return fail(f,TD3_FEED_ADC);
        /* Do not wait for the completed RMS window to detect a sampled peak. */
        if(fabsf(current[p])>=f->guard.limits.instantaneous_trip_a[p]) return fail(f,TD3_FEED_PEAK);
    }
    if(!motor_td3_thermal_window_add(&f->window,current,1)) return fail(f,TD3_FEED_ADC);
    f->sample_sequence=s->sequence;f->last_capture_us=s->capture_us;
    f->min_abs_speed_rpm=fminf(f->min_abs_speed_rpm,fabsf(s->speed_rpm));
    f->window_active|=s->output_active;
    if(f->window.samples<f->guard.limits.window_samples) return 1;
    if(!motor_td3_thermal_window_finish(&f->window,&o)) return fail(f,TD3_FEED_ADC);
    o.seq=f->guard.sequence+1;o.end_us=s->capture_us;
    o.output_active=f->window_active;o.min_abs_speed_rpm=f->min_abs_speed_rpm;
    if(!motor_td3_thermal_observe(&f->guard,&o,now)) return fail(f,TD3_FEED_THERMAL);
    motor_td3_thermal_window_init(&f->window);f->min_abs_speed_rpm=FLT_MAX;f->window_active=0;
    return 1;
}
int motor_td3_thermal_feed_may_start(motor_td3_thermal_feed *f,uint64_t now) {
    return motor_td3_thermal_feed_check(f,now)&&motor_td3_thermal_may_start(&f->guard,now);
}
