/* Synthetic numbers ONLY. No motor, register access or hardware approval. */
#include "motor_td3_thermal.h"
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static unsigned off_calls,test_count;
static void off(void *user) { assert(user==&off_calls);++off_calls; }
static motor_td3_thermal_limits limits(void) {
    motor_td3_thermal_limits l={ {1,1,1},{3,3,3},{1.5f,1.5f,1.5f},10,0.5f,
        125000,2,1000,10000000,1000000,1 };
    return l;
}
static motor_td3_thermal fresh(motor_td3_thermal_limits l) {
    motor_td3_thermal g;motor_td3_thermal_seed seed={{0,0,0},0,0,1};
    unsigned n=off_calls;
    assert(motor_td3_thermal_init(&g,&l,&seed,0,off,&off_calls));
    assert(off_calls==n+1);assert(!motor_td3_thermal_may_start(&g,0));return g;
}
static motor_td3_thermal_observation obs(const motor_td3_thermal *g,float a,float b,float c,unsigned enabled) {
    motor_td3_thermal_observation o;
    memset(&o,0,sizeof(o));o.seq=g->sequence+1;o.end_us=g->last_end_us+g->limits.window_us;
    o.samples=g->limits.window_samples;o.valid=1;o.output_active=enabled;o.min_abs_speed_rpm=100;
    o.peak_abs_a[0]=fabsf(a);o.peak_abs_a[1]=fabsf(b);o.peak_abs_a[2]=fabsf(c);
    o.mean_square_a2[0]=a*a;o.mean_square_a2[1]=b*b;o.mean_square_a2[2]=c*c;return o;
}
static int step(motor_td3_thermal *g,float a,float b,float c,unsigned enabled) {
    motor_td3_thermal_observation o=obs(g,a,b,c,enabled);
    return motor_td3_thermal_observe(g,&o,o.end_us);
}
static void fault_is_off(motor_td3_thermal *g,unsigned expected,unsigned before) {
    assert(g->fault==expected);assert(off_calls>before);
    assert(!motor_td3_thermal_may_start(g,g->last_now_us));
}
int main(void) {
    motor_td3_thermal_limits l=limits();motor_td3_thermal g;motor_td3_thermal_observation o;
    motor_td3_thermal_seed seed={{0,0,0},0,0,0};motor_td3_thermal_window w;
    float a[3]={2,-2,0};unsigned i,p,n;
    /* Known state is mandatory, even with valid limits. */
    n=off_calls;assert(!motor_td3_thermal_init(&g,&l,&seed,0,off,&off_calls));
    fault_is_off(&g,TD3_THERMAL_BOOT_UNKNOWN,n);++test_count;
    /* Every unconfigured/default parameter refuses operation. */
    for(i=0;i<13;++i) {
        motor_td3_thermal_limits bad=l;seed.known=1;
        switch(i) {
        case 0:bad.validated=0;break;case 1:bad.window_us=0;break;
        case 2:bad.window_samples=0;break;case 3:bad.max_energized_us=0;break;
        case 4:bad.max_stalled_us=0;break;case 5:bad.max_stalled_us=bad.max_energized_us+1;break;
        case 6:bad.continuous_rms_a[1]=NAN;break;case 7:bad.budget_a2s[2]=0;break;
        case 8:bad.instantaneous_trip_a[0]=INFINITY;break;case 9:bad.stall_rms_a=0;break;
        case 10:bad.stall_speed_rpm=-1;break;case 11:bad.instantaneous_trip_a[0]=1;break;
        default:bad.stall_rms_a=FLT_MAX;break;
        }
        n=off_calls;assert(!motor_td3_thermal_init(&g,&bad,&seed,0,off,&off_calls));
        fault_is_off(&g,TD3_THERMAL_CONFIG,n);
    }
    ++test_count;
    /* Average currents cancel; their heating MUST NOT cancel. */
    motor_td3_thermal_window_init(&w);
    assert(motor_td3_thermal_window_add(&w,a,1));a[0]=-2;a[1]=2;
    assert(motor_td3_thermal_window_add(&w,a,1));memset(&o,0,sizeof(o));
    assert(motor_td3_thermal_window_finish(&w,&o));
    assert(o.samples==2&&o.mean_square_a2[0]==4&&o.mean_square_a2[1]==4&&o.mean_square_a2[2]==0);
    assert(o.peak_abs_a[0]==2);++test_count;
    /* Collector faults latch and do not report a partially valid frame. */
    for(i=0;i<5;++i) {
        float bad[3]={1,1,1};motor_td3_thermal_window_init(&w);
        if(i==0) bad[0]=NAN;
        if(i==1) bad[1]=INFINITY;
        if(i==2) bad[2]=FLT_MAX;
        if(i==4) w.samples=UINT32_MAX;
        assert(!motor_td3_thermal_window_add(&w,bad,i!=3));
        assert(!motor_td3_thermal_window_add(&w,a,1));
        assert(!motor_td3_thermal_window_finish(&w,&o));assert(!o.valid);
    }
    ++test_count;
    /* Per-phase excess = (4-1)*0.125 = 0.375 A^2 s. Trip at 0.5 s. */
    for(p=0;p<3;++p) {
        float v[3]={0,0,0};g=fresh(l);v[p]=2;
        for(i=0;i<3;++i) assert(step(&g,v[0],v[1],v[2],1));
        assert(fabs(g.used_a2s[p]-1.125)<1e-6);n=off_calls;
        assert(!step(&g,v[0],v[1],v[2],1));fault_is_off(&g,TD3_THERMAL_BUDGET,n);
        assert(g.used_a2s[p]==1.5f);assert(motor_td3_thermal_load(&g)==1);
    }
    ++test_count;
    /* STOP, low current and a new experiment do not erase budget. */
    g=fresh(l);assert(step(&g,2,-2,0,1));
    for(i=0;i<4;++i) assert(step(&g,0,0,0,0));
    assert(g.used_a2s[0]==0.375f&&g.energized_us==125000);
    assert(motor_td3_thermal_may_start(&g,g.last_end_us));
    assert(step(&g,2,-2,0,1));assert(g.used_a2s[0]==0.75f);++test_count;
    /* Continuous RMS load does not add excess budget. */
    g=fresh(l);for(i=0;i<10;++i) assert(step(&g,1,-1,0,1));
    assert(motor_td3_thermal_load(&g)==0);++test_count;
    /* Same constant current, two window lengths, same integration. */
    g=fresh(l);assert(step(&g,1.5f,-1.5f,0,1));
    {
        motor_td3_thermal_limits shorter=l;motor_td3_thermal other;
        shorter.window_us/=2;other=fresh(shorter);
        assert(step(&other,1.5f,-1.5f,0,1));assert(step(&other,1.5f,-1.5f,0,1));
        assert(fabs(g.used_a2s[0]-other.used_a2s[0])<1e-6);
    }
    ++test_count;
    /* Bad / clipped / inconsistent / missing observations disable. */
    for(i=0;i<10;++i) {
        g=fresh(l);o=obs(&g,0,0,0,0);
        switch(i) {
        case 0:o.valid=0;break;case 1:o.output_active=2;break;case 2:o.samples--;break;
        case 3:o.mean_square_a2[0]=NAN;break;case 4:o.mean_square_a2[1]=-1;break;
        case 5:o.peak_abs_a[2]=INFINITY;break;case 6:o.min_abs_speed_rpm=NAN;break;
        case 7:o.peak_abs_a[0]=-1;break;case 8:o.mean_square_a2[0]=1;break;
        default:o.min_abs_speed_rpm=-1;break;
        }
        n=off_calls;assert(!motor_td3_thermal_observe(&g,&o,o.end_us));
        fault_is_off(&g,TD3_THERMAL_SENSOR,n);
    }
    ++test_count;
    /* Sampled instantaneous threshold uses magnitude, not signed current. */
    for(p=0;p<3;++p) {
        float v[3]={0,0,0};g=fresh(l);v[p]=-3;n=off_calls;
        assert(!step(&g,v[0],v[1],v[2],1));fault_is_off(&g,TD3_THERMAL_CURRENT,n);
    }
    ++test_count;
    /* Sequence replay, loss and overflow cannot refresh the guard. */
    for(i=0;i<3;++i) {
        g=fresh(l);o=obs(&g,0,0,0,0);
        if(i==0) o.seq=0;
        if(i==1) o.seq=2;
        if(i==2) g.sequence=UINT64_MAX;
        n=off_calls;assert(!motor_td3_thermal_observe(&g,&o,o.end_us));
        fault_is_off(&g,TD3_THERMAL_SEQUENCE,n);
    }
    ++test_count;
    /* Future, shortened and stale windows are not valid timing evidence. */
    for(i=0;i<3;++i) {
        uint64_t now;g=fresh(l);o=obs(&g,0,0,0,0);now=o.end_us;
        if(i==0) o.end_us++;
        if(i==1) o.end_us--;
        if(i==2) now+=l.max_age_us+1;
        n=off_calls;assert(!motor_td3_thermal_observe(&g,&o,now));
        assert(g.fault&&off_calls>n);
    }
    ++test_count;
    /* Independent deadline catches absent ADC; late samples never revive. */
    g=fresh(l);assert(step(&g,0,0,0,0));o=obs(&g,0,0,0,0);n=off_calls;
    assert(!motor_td3_thermal_check(&g,o.end_us+l.max_age_us+1));
    fault_is_off(&g,TD3_THERMAL_STALE,n);
    assert(!motor_td3_thermal_observe(&g,&o,g.last_now_us));++test_count;
    /* Time rollback faults; equality at the scheduled window is accepted. */
    g=fresh(l);assert(motor_td3_thermal_check(&g,l.window_us));assert(step(&g,0,0,0,0));
    n=off_calls;assert(!motor_td3_thermal_check(&g,g.last_now_us-1));
    fault_is_off(&g,TD3_THERMAL_TIME,n);++test_count;
    /* Stall time is cumulative, including repeated low-current START/STOP. */
    {
        motor_td3_thermal_limits stall=l;stall.max_stalled_us=250000;g=fresh(stall);
        o=obs(&g,0.5f,-0.5f,0,1);o.min_abs_speed_rpm=10;
        assert(motor_td3_thermal_observe(&g,&o,o.end_us));
        assert(step(&g,0,0,0,0));assert(step(&g,0.5f,-0.5f,0,1));
        o=obs(&g,0.5f,-0.5f,0,1);o.min_abs_speed_rpm=0;n=off_calls;
        assert(!motor_td3_thermal_observe(&g,&o,o.end_us));fault_is_off(&g,TD3_THERMAL_STALL,n);
        assert(g.stalled_us==250000);
    }
    ++test_count;
    /* Independent total energized-time cap, even at low current. */
    {
        motor_td3_thermal_limits timed=l;timed.max_energized_us=250000;timed.max_stalled_us=250000;
        g=fresh(timed);assert(step(&g,0,0,0,1));assert(step(&g,0,0,0,0));n=off_calls;
        assert(!step(&g,0,0,0,1));fault_is_off(&g,TD3_THERMAL_DURATION,n);
        assert(g.energized_us==250000);
    }
    ++test_count;
    /* A retained warm seed is loaded; invalid or already exhausted states fail. */
    seed.known=1;seed.used_a2s[0]=1.125f;
    assert(motor_td3_thermal_init(&g,&l,&seed,0,off,&off_calls));n=off_calls;
    assert(!step(&g,2,0,0,1));fault_is_off(&g,TD3_THERMAL_BUDGET,n);
    for(i=0;i<4;++i) {
        motor_td3_thermal_seed bad={{0,0,0},0,0,1};
        if(i==0) bad.used_a2s[0]=NAN;
        if(i==1) bad.used_a2s[1]=-1;
        if(i==2) bad.used_a2s[2]=1.5f;
        if(i==3) bad.stalled_us=1;
        n=off_calls;assert(!motor_td3_thermal_init(&g,&l,&bad,0,off,&off_calls));
        assert(g.fault&&off_calls>n);
    }
    ++test_count;
    printf("{\"schema_version\":1,\"test_groups\":%u,\"passed\":true,"
           "\"hardware_accessed\":false,\"thermal_protection_verified\":false,"
           "\"motion_authorized\":false,\"synthetic_parameters_only\":true}\n",test_count);
    return 0;
}
