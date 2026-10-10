#include "motor_td3_speedloop_pi.h"
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if(!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1); } } while(0)
#define RUN(fn) do { fn();++tests; } while(0)
static unsigned tests;
static motor_td3_speedloop_pi s;
static float integral,kp,ki;
static const motor_td3_speedloop_pi_domain domain={.001f,.006f,.0005f,.003f};
static void fresh(void) {
    CHECK(motor_td3_speedloop_pi_init(&s,&domain));
    integral=.4f;kp=TD3_SPEEDLOOP_KP;ki=TD3_SPEEDLOOP_KI;
}
static int boundary(uint64_t t,float e,int reset) {
    return motor_td3_speedloop_pi_boundary(&s,t,e,reset,&integral,&kp,&ki);
}
static void queue(uint32_t seq,uint64_t deadline) {
    CHECK(motor_td3_speedloop_pi_stage(&s,TD3_SPEEDLOOP_EXTERNAL,seq,.004f,.002f,deadline));
}
static void uninitialized_rejected(void) {
    memset(&s,0,sizeof(s));CHECK(!motor_td3_speedloop_pi_stage(&s,2,1,.004f,.002f,5000));
    CHECK(s.fault==TD3_PI_ARGUMENT);
}
static void domain_rejected(void) {
    motor_td3_speedloop_pi_domain d=domain;d.ki_max=NAN;
    CHECK(!motor_td3_speedloop_pi_init(&s,&d)&&s.fault==TD3_PI_ARGUMENT);
    d=domain;d.kp_min=.004f;
    CHECK(!motor_td3_speedloop_pi_init(&s,&d)&&s.fault==TD3_PI_RANGE);
}
static void queued_pair_is_not_applied(void) {
    fresh();queue(7,5000);CHECK(s.pending&&s.applied_seq==0&&s.mode==0);
    CHECK(kp==TD3_SPEEDLOOP_KP&&ki==TD3_SPEEDLOOP_KI&&s.deadline_us==0);
}
static void paired_commit_with_ack(void) {
    fresh();queue(7,5000);CHECK(boundary(1000,100,0));
    CHECK(kp==.004f&&ki==.002f&&s.applied_seq==7&&s.applied_us==1000);
    CHECK(s.mode==2&&!s.pending&&s.deadline_us==5000);
}
static void positive_continuity(void) {
    fresh();queue(1,5000);float old=kp*100+integral;
    CHECK(boundary(1000,100,0));CHECK(fabsf(old-(kp*100+integral))<1e-6f);
}
static void negative_continuity(void) {
    fresh();queue(1,5000);float old=kp*-250+integral;
    CHECK(boundary(1000,-250,0));CHECK(fabsf(old-(kp*-250+integral))<1e-6f);
}
static void saturated_continuity(void) {
    fresh();integral=2;queue(1,5000);CHECK(boundary(1000,1000,0));
    CHECK(s.sum_before>3&&fabsf(s.sum_before-s.sum_after)<1e-6f);
}
static void ki_alone_does_not_rescale_integral(void) {
    fresh();CHECK(motor_td3_speedloop_pi_stage(&s,1,1,kp,.002f,5000));
    CHECK(boundary(1000,100,0));CHECK(integral==.4f&&ki==.002f&&s.mode==1);
}
static void reset_has_priority(void) {
    fresh();queue(1,5000);CHECK(boundary(1000,100,1));
    CHECK(s.applied_seq==0&&s.pending&&integral==.4f&&kp==TD3_SPEEDLOOP_KP);
    CHECK(boundary(2000,100,0)&&s.applied_seq==1);
}
static void reset_does_not_extend_pending_lease(void) {
    fresh();queue(1,2000);CHECK(boundary(1000,100,1));
    CHECK(!boundary(2000,100,1)&&s.fault==TD3_PI_EXPIRED&&s.applied_seq==0);
}
static void active_lease_expires(void) {
    fresh();queue(1,2000);CHECK(boundary(1000,100,0));
    CHECK(!boundary(2000,100,0)&&s.fault==TD3_PI_EXPIRED);
}
static void pending_cannot_extend_active_lease(void) {
    fresh();queue(1,2000);CHECK(boundary(1000,100,0));queue(2,9000);
    CHECK(!boundary(2000,100,1)&&s.fault==TD3_PI_EXPIRED&&s.applied_seq==1);
}
static void replay_rejected(void) {
    fresh();queue(7,5000);CHECK(boundary(1000,100,0));
    CHECK(!motor_td3_speedloop_pi_stage(&s,2,7,.004f,.002f,5000)&&s.fault==TD3_PI_SEQUENCE);
}
static void queue_overwrite_rejected(void) {
    fresh();queue(1,5000);
    CHECK(!motor_td3_speedloop_pi_stage(&s,2,2,.004f,.002f,6000)&&s.fault==TD3_PI_BUSY);
    CHECK(s.applied_seq==0&&!s.pending);
}
static void bad_gain_is_not_partially_applied(void) {
    fresh();CHECK(!motor_td3_speedloop_pi_stage(&s,2,1,.004f,NAN,5000));
    CHECK(s.fault==TD3_PI_RANGE&&kp==TD3_SPEEDLOOP_KP&&ki==TD3_SPEEDLOOP_KI);
}
static void bad_input_is_not_partially_applied(void) {
    fresh();queue(1,5000);CHECK(!boundary(1000,NAN,0));
    CHECK(s.fault==TD3_PI_NUMERIC&&integral==.4f&&kp==TD3_SPEEDLOOP_KP&&s.applied_seq==0);
}
static void overflow_is_not_partially_applied(void) {
    fresh();queue(1,5000);kp=2;CHECK(!boundary(1000,FLT_MAX,0));
    CHECK(s.fault==TD3_PI_NUMERIC&&integral==.4f&&kp==2&&ki==TD3_SPEEDLOOP_KI);
}
static void unexpected_owner_write_rejected(void) {
    fresh();queue(1,5000);CHECK(boundary(1000,100,0));ki=.001f;
    CHECK(!boundary(2000,100,0)&&s.fault==TD3_PI_OWNER);
}
static void clock_reversal_rejected(void) {
    fresh();CHECK(boundary(1000,100,0));CHECK(!boundary(999,100,0)&&s.fault==TD3_PI_CLOCK);
}
static void fault_stays_latched(void) {
    fresh();queue(1,1000);CHECK(!boundary(1000,100,0));
    CHECK(!motor_td3_speedloop_pi_stage(&s,2,2,.004f,.002f,9000));
    CHECK(!boundary(2000,100,0)&&s.fault==TD3_PI_EXPIRED&&s.applied_seq==0);
}
int main(void) {
    RUN(uninitialized_rejected);RUN(domain_rejected);RUN(queued_pair_is_not_applied);
    RUN(paired_commit_with_ack);RUN(positive_continuity);RUN(negative_continuity);
    RUN(saturated_continuity);RUN(ki_alone_does_not_rescale_integral);RUN(reset_has_priority);
    RUN(reset_does_not_extend_pending_lease);RUN(active_lease_expires);RUN(pending_cannot_extend_active_lease);
    RUN(replay_rejected);RUN(queue_overwrite_rejected);RUN(bad_gain_is_not_partially_applied);
    RUN(bad_input_is_not_partially_applied);RUN(overflow_is_not_partially_applied);
    RUN(unexpected_owner_write_rejected);RUN(clock_reversal_rejected);RUN(fault_stays_latched);
    printf("{\"tests\":%u,\"passed\":true}\n",tests);return 0;
}
