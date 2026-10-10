/* Synthetic calibration/current/thermal limits ONLY; no hardware approval. */
#include "motor_td3_thermal_feed.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static unsigned off_calls,groups;
static void off(void *u) { assert(u==&off_calls);++off_calls; }
static motor_td3_current_calibration calibration(void) {
    motor_td3_current_calibration c={{2000,2010,2020},{.01f,.02f,.025f},
        {1000,1000,1000},{3000,3000,3000},1};return c;
}
static motor_td3_thermal_limits limits(void) {
    motor_td3_thermal_limits l={{1,1,1},{4,4,4},{1.5f,1.5f,1.5f},10,.5f,
        1000,10,25,1000000,100000,1};return l;
}
static motor_td3_thermal_feed fresh(motor_td3_thermal_limits l) {
    motor_td3_thermal_feed f={0};motor_td3_current_calibration c=calibration();
    motor_td3_thermal_seed seed={{0,0,0},0,0,1};unsigned n=off_calls;
    assert(motor_td3_thermal_feed_init(&f,&c,&l,&seed,0,off,&off_calls));
    assert(off_calls>n);assert(!motor_td3_thermal_feed_may_start(&f,0));return f;
}
static motor_td3_thermal_sample sample(motor_td3_thermal_feed *f,int a,int b,int c) {
    motor_td3_thermal_sample s={0};s.sequence=f->sample_sequence+1;
    s.capture_us=f->last_capture_us+f->period_us;s.valid=1;s.speed_rpm=100;
    s.raw_adc[0]=(uint16_t)(2000+a);s.raw_adc[1]=(uint16_t)(2010+b);s.raw_adc[2]=(uint16_t)(2020+c);return s;
}
static int submit(motor_td3_thermal_feed *f,int a,int b,int c,unsigned active) {
    motor_td3_thermal_sample s=sample(f,a,b,c);s.output_active=active;
    return motor_td3_thermal_feed_sample(f,&s,s.capture_us);
}
static void latched(motor_td3_thermal_feed *f,unsigned reason,unsigned n) {
    assert(f->fault==reason&&off_calls>n);
    assert(!motor_td3_thermal_feed_may_start(f,f->last_now_us));
    assert(!motor_td3_thermal_may_start(&f->guard,f->last_now_us));
}
int main(void) {
    motor_td3_thermal_limits l=limits();motor_td3_current_calibration c=calibration();
    motor_td3_thermal_seed seed={{0,0,0},0,0,1};motor_td3_thermal_feed f;
    motor_td3_thermal_sample s;unsigned i,p,n;
    /* Nominal numeric gains do not count as measured calibration. */
    f=(motor_td3_thermal_feed){0};c.calibrated=0;n=off_calls;
    assert(!motor_td3_thermal_feed_init(&f,&c,&l,&seed,0,off,&off_calls));
    latched(&f,TD3_FEED_CALIBRATION,n);++groups;
    /* Missing, nonfinite and unmeasured raw domains fail closed. */
    for(i=0;i<8;++i) {
        c=calibration();f=(motor_td3_thermal_feed){0};n=off_calls;
        switch(i) {
        case 0:c.zero_adc[0]=NAN;break;case 1:c.gain_a_per_count[1]=INFINITY;break;
        case 2:c.gain_a_per_count[2]=0;break;case 3:c.gain_a_per_count[0]=-1;break;
        case 4:c.verified_low_adc[0]=0;break;case 5:c.verified_high_adc[2]=4095;break;
        case 6:c.zero_adc[1]=c.verified_low_adc[1];break;
        default:c.zero_adc[2]=c.verified_high_adc[2];break;
        }
        assert(!motor_td3_thermal_feed_init(&f,&c,&l,&seed,0,off,&off_calls));
        latched(&f,TD3_FEED_CALIBRATION,n);
    }
    ++groups;
    c=calibration();seed.known=0;f=(motor_td3_thermal_feed){0};n=off_calls;
    assert(!motor_td3_thermal_feed_init(&f,&c,&l,&seed,0,off,&off_calls));
    latched(&f,TD3_FEED_THERMAL,n);assert(f.guard.fault==TD3_THERMAL_BOOT_UNKNOWN);++groups;
    seed.known=1;{ motor_td3_thermal_limits bad=l;bad.validated=0;f=(motor_td3_thermal_feed){0};n=off_calls;
        assert(!motor_td3_thermal_feed_init(&f,&c,&bad,&seed,0,off,&off_calls));
        latched(&f,TD3_FEED_THERMAL,n);assert(f.guard.fault==TD3_THERMAL_CONFIG); }
    ++groups;
    /* Different per-phase gains and alternating signs, followed by RMS budget. */
    f=fresh(l);
    for(i=0;i<10;++i) { int sign=i%2?1:-1;assert(submit(&f,sign*200,sign*100,sign*60,1)); }
    assert(f.guard.has_window&&f.guard.sequence==1);
    assert(fabs(f.guard.used_a2s[0]-.003)<1e-7&&fabs(f.guard.used_a2s[1]-.003)<1e-7);
    assert(fabs(f.guard.used_a2s[2]-.00125)<1e-7);assert(f.guard.energized_us==1000);
    assert(motor_td3_thermal_feed_may_start(&f,1000));++groups;
    for(i=0;i<3;++i) {
        f=fresh(l);s=sample(&f,0,0,0);n=off_calls;
        if(i==0)s.sequence=0;
        if(i==1)s.sequence=2;
        if(i==2)f.sample_sequence=UINT64_MAX;
        assert(!motor_td3_thermal_feed_sample(&f,&s,s.capture_us));latched(&f,TD3_FEED_SEQUENCE,n);
    }
    ++groups;
    for(p=0;p<3;++p) for(i=0;i<4;++i) {
        f=fresh(l);s=sample(&f,0,0,0);n=off_calls;
        s.raw_adc[p]=(uint16_t)(i==0?0:i==1?4095:i==2?999:3001);
        assert(!motor_td3_thermal_feed_sample(&f,&s,s.capture_us));latched(&f,TD3_FEED_ADC,n);
    }
    ++groups;
    for(i=0;i<5;++i) {
        f=fresh(l);s=sample(&f,0,0,0);n=off_calls;
        if(i==0)s.valid=0;
        if(i==1)s.valid=2;
        if(i==2)s.speed_rpm=NAN;
        if(i==3)s.speed_rpm=INFINITY;
        if(i==4)s.output_active=2;
        assert(!motor_td3_thermal_feed_sample(&f,&s,s.capture_us));latched(&f,TD3_FEED_ADC,n);
    }
    ++groups;
    for(i=0;i<3;++i) {
        f=fresh(l);s=sample(&f,0,0,0);n=off_calls;
        if(i==0)--s.capture_us;
        if(i==1)++s.capture_us;
        assert(!motor_td3_thermal_feed_sample(&f,&s,i==2?99:100));latched(&f,TD3_FEED_TIME,n);
    }
    ++groups;
    for(p=0;p<3;++p) for(i=0;i<2;++i) {
        static const int delta[3]={400,200,160};f=fresh(l);s=sample(&f,0,0,0);n=off_calls;
        s.raw_adc[p]=(uint16_t)(c.zero_adc[p]+(i?delta[p]:-delta[p]));
        assert(!motor_td3_thermal_feed_sample(&f,&s,100));latched(&f,TD3_FEED_PEAK,n);
        assert(!f.window.samples&&!f.guard.has_window);
    }
    ++groups;
    f=fresh(l);n=off_calls;assert(!motor_td3_thermal_feed_check(&f,126));latched(&f,TD3_FEED_STALE,n);
    s=sample(&f,0,0,0);assert(!motor_td3_thermal_feed_sample(&f,&s,126));assert(f.fault==TD3_FEED_STALE);++groups;
    /* Deadline equality permits checker-before-observer with bounded latency. */
    f=fresh(l);s=sample(&f,0,0,0);assert(motor_td3_thermal_feed_check(&f,125));
    assert(motor_td3_thermal_feed_sample(&f,&s,125));++groups;
    /* STOP samples retain budget; init cannot erase it. */
    f=fresh(l);for(i=0;i<10;++i)assert(submit(&f,200,0,0,1));
    for(i=0;i<10;++i)assert(submit(&f,0,0,0,0));
    assert(fabs(f.guard.used_a2s[0]-.003)<1e-7&&f.guard.energized_us==1000);n=off_calls;
    assert(!motor_td3_thermal_feed_init(&f,&c,&l,&seed,2000,off,&off_calls));
    latched(&f,TD3_FEED_INIT,n);assert(fabs(f.guard.used_a2s[0]-.003)<1e-7);++groups;
    /* Any active interval and minimum speed charge a conservative whole window. */
    { motor_td3_thermal_limits stall=l;stall.max_stalled_us=1000;f=fresh(stall);
        for(i=0;i<10;++i) { s=sample(&f,100,0,0);s.output_active=i==0;s.speed_rpm=i==9?0:100;
            if(i<9)assert(motor_td3_thermal_feed_sample(&f,&s,s.capture_us));
            else assert(!motor_td3_thermal_feed_sample(&f,&s,s.capture_us)); }
        assert(f.guard.fault==TD3_THERMAL_STALL&&f.guard.energized_us==1000&&f.guard.stalled_us==1000); }
    ++groups;
    for(p=0;p<3;++p) {
        motor_td3_thermal_limits small=l;small.budget_a2s[p]=.005f;f=fresh(small);
        for(i=0;i<20&&!f.fault;++i)assert(submit(&f,p==0?200:0,p==1?100:0,p==2?80:0,0)==(i<19));
        assert(f.fault==TD3_FEED_THERMAL&&f.guard.fault==TD3_THERMAL_BUDGET);
    }
    ++groups;
    f=fresh(l);assert(submit(&f,0,0,0,0));n=off_calls;
    assert(!motor_td3_thermal_feed_check(&f,99));latched(&f,TD3_FEED_TIME,n);++groups;
    f=(motor_td3_thermal_feed){0};assert(motor_td3_thermal_feed_init(&f,&c,&l,&seed,UINT64_MAX-50,off,&off_calls));
    s=(motor_td3_thermal_sample){1,UINT64_MAX,{2000,2010,2020},100,1,0};n=off_calls;
    assert(!motor_td3_thermal_feed_sample(&f,&s,UINT64_MAX));latched(&f,TD3_FEED_TIME,n);++groups;
    printf("{\"schema_version\":1,\"test_groups\":%u,\"passed\":true,\"hardware_accessed\":false,"
           "\"synthetic_parameters_only\":true,\"current_gain_calibrated\":false,\"thermal_protection_verified\":false}\n",groups);
    return 0;
}
