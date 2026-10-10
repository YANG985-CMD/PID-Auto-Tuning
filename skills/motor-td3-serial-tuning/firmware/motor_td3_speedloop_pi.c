#include "motor_td3_speedloop_pi.h"
#include <math.h>
#include <string.h>

static int fail(motor_td3_speedloop_pi *s,unsigned fault) {
    if(s) { if(!s->fault) s->fault=fault;s->pending=0; }
    return 0;
}
static int valid(const motor_td3_speedloop_pi *s,float kp,float ki) {
    return isfinite(kp)&&isfinite(ki)&&kp>=s->domain.kp_min&&kp<=s->domain.kp_max&&
           ki>=s->domain.ki_min&&ki<=s->domain.ki_max;
}
int motor_td3_speedloop_pi_init(motor_td3_speedloop_pi *s,const motor_td3_speedloop_pi_domain *d) {
    if(!s) return 0;
    memset(s,0,sizeof(*s));
    if(!d||!isfinite(d->kp_min)||!isfinite(d->kp_max)||!isfinite(d->ki_min)||!isfinite(d->ki_max)||
       d->kp_min<0||d->ki_min<0||d->kp_min>d->kp_max||d->ki_min>d->ki_max)
        return fail(s,TD3_PI_ARGUMENT);
    s->domain=*d;
    if(!valid(s,TD3_SPEEDLOOP_KP,TD3_SPEEDLOOP_KI)) return fail(s,TD3_PI_RANGE);
    s->actual_kp=TD3_SPEEDLOOP_KP;s->actual_ki=TD3_SPEEDLOOP_KI;
    s->initialized=1;
    return 1;
}
int motor_td3_speedloop_pi_stage(motor_td3_speedloop_pi *s,unsigned mode,uint32_t seq,
                               float kp,float ki,uint64_t deadline_us) {
    if(!s||s->fault) return 0;
    if(!s->initialized) return fail(s,TD3_PI_ARGUMENT);
    if(mode!=TD3_SPEEDLOOP_FIXED&&mode!=TD3_SPEEDLOOP_EXTERNAL) return fail(s,TD3_PI_ARGUMENT);
    if(!valid(s,kp,ki)) return fail(s,TD3_PI_RANGE);
    if(!seq||seq<=s->last_queued_seq) return fail(s,TD3_PI_SEQUENCE);
    if(s->pending) return fail(s,TD3_PI_BUSY);
    if(deadline_us<=s->control_us) return fail(s,TD3_PI_EXPIRED);
    s->pending_kp=kp;s->pending_ki=ki;s->pending_mode=mode;
    s->last_queued_seq=seq;s->pending_deadline_us=deadline_us;s->pending=1;
    return 1;
}
int motor_td3_speedloop_pi_boundary(motor_td3_speedloop_pi *s,uint64_t now_us,float error,
                                  int reset,float *integral,float *kp,float *ki) {
    float next_i,before,after;
    if(!s||s->fault) return 0;
    if(!s->initialized) return fail(s,TD3_PI_ARGUMENT);
    if(!integral||!kp||!ki||!isfinite(error)||!isfinite(*integral)||!isfinite(*kp)||!isfinite(*ki))
        return fail(s,TD3_PI_NUMERIC);
    if(now_us<=s->control_us) return fail(s,TD3_PI_CLOCK);
    if(s->mode!=TD3_SPEEDLOOP_FUZZY&&(*kp!=s->actual_kp||*ki!=s->actual_ki))
        return fail(s,TD3_PI_OWNER);
    /* Queuing a replacement must not extend the currently applied lease. */
    if((s->pending&&now_us>=s->pending_deadline_us)||
       (s->mode!=TD3_SPEEDLOOP_FUZZY&&now_us>=s->deadline_us))
        return fail(s,TD3_PI_EXPIRED);
    before=*kp*error+*integral;
    if(!isfinite(before)) return fail(s,TD3_PI_NUMERIC);
    if(s->pending&&!reset) {
        next_i=*integral+(*kp-s->pending_kp)*error;
        after=s->pending_kp*error+next_i;
        if(!isfinite(next_i)||!isfinite(after)) return fail(s,TD3_PI_NUMERIC);
        /* Commit only after every check. Ki is continuous: the model owns Ts.
         * integral is already the integrator OUTPUT, so do not scale it by Ki. */
        *integral=next_i;*kp=s->pending_kp;*ki=s->pending_ki;
        s->mode=s->pending_mode;s->applied_seq=s->last_queued_seq;s->applied_us=now_us;
        s->deadline_us=s->pending_deadline_us;s->pending=0;
    }
    s->control_us=now_us;s->actual_kp=*kp;s->actual_ki=*ki;s->integral_output=*integral;
    s->sum_before=before;s->sum_after=*kp*error+*integral;
    return 1;
}
