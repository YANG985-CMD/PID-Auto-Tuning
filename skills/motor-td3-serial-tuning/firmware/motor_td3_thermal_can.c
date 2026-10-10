#include "motor_td3_thermal_can.h"
#include <float.h>
#include <math.h>
#include <string.h>
typedef char ieee32_required[(sizeof(float)==4 && FLT_RADIX==2 && FLT_MANT_DIG==24)?1:-1];
typedef char ieee64_required[(sizeof(double)==8 && DBL_MANT_DIG==53)?1:-1];
static void put32(uint8_t *p,uint32_t v) {
    unsigned i;for(i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i));
}
static void put64(uint8_t *p,uint64_t v) { put32(p,(uint32_t)v);put32(p+4,(uint32_t)(v>>32)); }
static void real32(uint8_t *p,float v) { uint32_t u;memcpy(&u,&v,4);put32(p,u); }
static void real64(uint8_t *p,double v) { uint64_t u;memcpy(&u,&v,8);put64(p,u); }
static uint32_t crc(const uint8_t *p,unsigned n) {
    uint32_t c=0xffffffffU;unsigned i,k;
    for(i=0;i<n;++i) { c^=p[i];for(k=0;k<8;++k) c=(c>>1)^((c&1)?0xedb88320U:0U); }
    return c^0xffffffffU;
}
int motor_td3_thermal_can_packet(uint8_t out[TD3_THERMAL_CAN_BYTES],
    const motor_td3_thermal_feed *f,uint64_t nonce,uint64_t boot,uint32_t seq,uint64_t now) {
    const motor_td3_thermal *g;unsigned flags=TD3_HEAT_LOCKED,p;
    uint32_t period=0;
    if(!out||!f||!nonce||!boot||!seq) return 0;
    g=&f->guard;
    if(f->fault>TD3_FEED_PEAK||g->fault>TD3_THERMAL_DURATION||
       (g->configured&&(!g->limits.window_samples||!g->limits.window_us||
        g->limits.window_us%g->limits.window_samples))) return 0;
    if(f->calibration.calibrated==1) flags|=TD3_HEAT_CALIBRATED;
    if(g->configured) { flags|=TD3_HEAT_LIMITS;period=g->limits.window_us/g->limits.window_samples; }
    if(g->seed_known) flags|=TD3_HEAT_SEED;
    if(g->configured&&g->seed_known) flags|=TD3_HEAT_ACCOUNTING;
    if(f->sample_sequence&&period) {
        flags|=TD3_HEAT_SAMPLE;
        if(now>=f->last_capture_us&&now-f->last_capture_us<=(uint64_t)period+g->limits.max_age_us)
            flags|=TD3_HEAT_SAMPLE_FRESH;
    }
    if(g->has_window) {
        flags|=TD3_HEAT_WINDOW;
        if(now>=g->last_end_us&&now-g->last_end_us<=(uint64_t)g->limits.window_us+g->limits.max_age_us)
            flags|=TD3_HEAT_WINDOW_FRESH;
    }
    memset(out,0,TD3_THERMAL_CAN_BYTES);memcpy(out,"THT1",4);
    out[4]=1;out[6]=TD3_THERMAL_CAN_BYTES;
    put64(out+8,nonce);put64(out+16,boot);put32(out+24,seq);put32(out+28,flags);
    out[32]=(uint8_t)f->fault;out[34]=(uint8_t)g->fault;
    put64(out+36,now);put64(out+44,f->sample_sequence);
    put64(out+52,(flags&TD3_HEAT_SAMPLE)?f->last_capture_us:UINT64_MAX);
    put64(out+60,g->sequence);put64(out+68,(flags&TD3_HEAT_WINDOW)?g->last_end_us:UINT64_MAX);
    for(p=0;p<3;++p) {
        real64(out+76+8*p,(flags&TD3_HEAT_ACCOUNTING)?g->used_a2s[p]:NAN);
        real32(out+100+4*p,(flags&TD3_HEAT_LIMITS)?g->limits.budget_a2s[p]:NAN);
    }
    put64(out+112,(flags&TD3_HEAT_ACCOUNTING)?g->energized_us:UINT64_MAX);
    put64(out+120,(flags&TD3_HEAT_ACCOUNTING)?g->stalled_us:UINT64_MAX);
    put32(out+128,period);put32(out+132,(flags&TD3_HEAT_LIMITS)?g->limits.max_age_us:0);
    put32(out+136,(flags&TD3_HEAT_LIMITS)?g->limits.window_us:0);
    put32(out+140,crc(out,140));return TD3_THERMAL_CAN_BYTES;
}
