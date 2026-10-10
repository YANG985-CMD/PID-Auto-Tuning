/* Tests link the user's actual generated model and actual fuzzy controller.
 * This file supplies synthetic observations, not a physical motor model. */
#include "FOC_Model.h"
#include "fuzzy_pid.h"
#include "motor_td3_speedloop_pi_bind.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

FuzzyPID_t fuzzy_speed_pid;
uint8_t Motor_state;
static uint64_t now_us;
static unsigned tests;
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1); } } while(0)
#define RUN(fn) do { fn();++tests; } while(0)
uint64_t motor_td3_speedloop_pi_host_time_us(void) { return now_us; }
static void fresh(void) {
    memset(&rtDW,0,sizeof(rtDW));memset(&rtU,0,sizeof(rtU));memset(&rtY,0,sizeof(rtY));
    memset(rtM,0,sizeof(*rtM));now_us=0;Motor_state=0;
    spd_kpki.spd_kp=TD3_SPEEDLOOP_KP;spd_kpki.spd_ki=TD3_SPEEDLOOP_KI;
    FOC_Model_initialize();FuzzyPID_Init(&fuzzy_speed_pid,TD3_SPEEDLOOP_KP,TD3_SPEEDLOOP_KI,0,500,100);
    motor_td3_speedloop_pi_bind_init();rtU.v_bus=24;rtU.SpeedRef=1000;
}
static void tick(float error) {
    now_us+=100;rtU.SpeedFd=1000-error;
    motor_td3_speedloop_pi_fast(error);FOC_Model_step();
}
static void speed(float error) {
    while(rtM->Timing.TaskCounters.TID[1]) tick(error);
    tick(error);
}
static void queue(float kp,float ki,uint64_t deadline) {
    CHECK(motor_td3_speedloop_pi_queue(2,1,kp,ki,deadline));
}
static void applied_at_actual_one_ms_boundary(void) {
    fresh();tick(100);queue(.004f,.002f,10000);
    for(unsigned i=0;i<9;++i) { tick(100);CHECK(motor_td3_speedloop_pi_state.applied_seq==0); }
    tick(100);CHECK(motor_td3_speedloop_pi_state.applied_seq==1);
    CHECK(motor_td3_speedloop_pi_state.applied_us==1100&&spd_kpki.spd_kp==.004f&&spd_kpki.spd_ki==.002f);
}
static void init_reset_postpones_change(void) {
    fresh();queue(.004f,.002f,10000);tick(100);
    CHECK(motor_td3_speedloop_pi_state.applied_seq==0&&motor_td3_speedloop_pi_state.pending);
    speed(100);CHECK(motor_td3_speedloop_pi_state.applied_seq==1);
}
static void previous_derivative_and_output_continuity(void) {
    fresh();tick(100);rtDW.Integrator_DSTATE_h=.5f;rtDW.Integrator_PREV_U=.2f;
    queue(.004f,.002f,10000);speed(100);
    float expected=.5002f+(fuzzy_speed_pid.Kp-.004f)*100;
    CHECK(fabsf(rtDW.Integrator_DSTATE_h-expected)<2e-6f);
    CHECK(fabsf(motor_td3_speedloop_pi_state.sum_after-motor_td3_speedloop_pi_state.sum_before)<2e-6f);
}
static void ki_is_continuous_and_model_applies_ts_once(void) {
    fresh();tick(100);queue(.004f,.002f,10000);speed(100);
    CHECK(fabsf(rtDW.Integrator_PREV_U-.2f)<1e-6f);
    float old_i=rtDW.Integrator_DSTATE_h;speed(100);
    CHECK(fabsf(rtDW.Integrator_DSTATE_h-(old_i+.0002f))<1e-6f);
}
static void fuzzy_cannot_overwrite_external_pair(void) {
    fresh();tick(100);queue(.004f,.002f,10000);speed(100);
    float last=fuzzy_speed_pid.e_last;
    for(unsigned i=0;i<20;++i) { tick(-300);CHECK(spd_kpki.spd_kp==.004f&&spd_kpki.spd_ki==.002f); }
    CHECK(fuzzy_speed_pid.e_last==last&&motor_td3_speedloop_pi_state.fault==0);
}
static void generated_reset_has_priority(void) {
    fresh();tick(100);rtDW.Integrator_DSTATE_h=.8f;rtDW.Integrator_PREV_U=.2f;
    rtDW.SpeedReset=1;rtDW.Integrator_PrevResetState=0;
    queue(.004f,.002f,10000);speed(100);
    CHECK(rtDW.Integrator_DSTATE_h==0&&motor_td3_speedloop_pi_state.applied_seq==0);
    rtDW.SpeedReset=0;speed(100);CHECK(motor_td3_speedloop_pi_state.applied_seq==1);
}
static void positive_saturation_retains_antiwindup(void) {
    fresh();tick(1000);rtDW.Integrator_DSTATE_h=2;rtDW.Integrator_PREV_U=0;
    queue(.004f,.002f,10000);speed(1000);
    CHECK(rtDW.Saturation==3&&rtDW.Integrator_PREV_U==0);
    CHECK(fabsf(motor_td3_speedloop_pi_state.sum_before-motor_td3_speedloop_pi_state.sum_after)<2e-6f);
}
static void negative_saturation_retains_antiwindup(void) {
    fresh();tick(-1000);rtDW.Integrator_DSTATE_h=-2;rtDW.Integrator_PREV_U=0;
    queue(.004f,.002f,10000);speed(-1000);
    CHECK(rtDW.Saturation==-3&&rtDW.Integrator_PREV_U==0);
}
static void numeric_fault_clears_start_flags(void) {
    fresh();tick(100);rtU.Motor_OnOff=1;Motor_state=255;
    motor_td3_speedloop_pi_fast(NAN);
    CHECK(!rtU.Motor_OnOff&&!Motor_state&&motor_td3_speedloop_pi_state.fault==TD3_PI_NUMERIC);
    CHECK(!motor_td3_speedloop_pi_queue(2,1,.004f,.002f,10000));
}
static void expired_action_exits_actual_model_task(void) {
    fresh();tick(100);queue(.004f,.002f,1100);rtU.Motor_OnOff=1;Motor_state=255;
    uint32_t old_clock=rtM->Timing.clockTick1;speed(100);
    CHECK(motor_td3_speedloop_pi_state.fault==TD3_PI_EXPIRED&&!rtU.Motor_OnOff&&!Motor_state);
    CHECK(rtM->Timing.clockTick1==old_clock&&motor_td3_speedloop_pi_state.applied_seq==0);
}
int main(void) {
    RUN(applied_at_actual_one_ms_boundary);RUN(init_reset_postpones_change);
    RUN(previous_derivative_and_output_continuity);RUN(ki_is_continuous_and_model_applies_ts_once);
    RUN(fuzzy_cannot_overwrite_external_pair);RUN(generated_reset_has_priority);
    RUN(positive_saturation_retains_antiwindup);RUN(negative_saturation_retains_antiwindup);
    RUN(numeric_fault_clears_start_flags);RUN(expired_action_exits_actual_model_task);
    printf("{\"tests\":%u,\"passed\":true}\n",tests);return 0;
}
