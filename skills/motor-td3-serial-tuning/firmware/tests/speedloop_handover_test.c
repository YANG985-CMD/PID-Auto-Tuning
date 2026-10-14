#include "FOC_Model.h"
#include "fuzzy_pid.h"
#include "motor_td3_speedloop_pi_bind.h"
#include "motor_td3_startup_handover.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
FuzzyPID_t fuzzy_speed_pid;
uint8_t Motor_state;
static uint64_t now_us;
uint64_t motor_td3_speedloop_pi_host_time_us(void) {return now_us;}
static float difference(float x,float y) {return atan2f(sinf(x-y),cosf(x-y));}
static void fresh(void) {
    memset(&rtDW,0,sizeof(rtDW));memset(&rtU,0,sizeof(rtU));memset(&rtY,0,sizeof(rtY));memset(rtM,0,sizeof(*rtM));
    now_us=0;FOC_Model_initialize();FuzzyPID_Init(&fuzzy_speed_pid,.003389f,.00144f,0,500,100);
    motor_td3_speedloop_pi_bind_init();rtU.Motor_OnOff=1;rtU.v_bus=24;rtU.SpeedRef=1000;
}
int main(void) {
    for(unsigned sign=0;sign<2;sign++) {
        motor_td3_startup_handover_reset();
        float old=6.2f,hall=old+(sign?1.64f:-1.64f);
        motor_td3_startup_handover_angle(3,old,hall);
        float first=motor_td3_startup_handover_angle(4,hall,hall);
        assert(fabsf(difference(first,old))<2e-6f);
        float prev=first;
        for(unsigned j=1;j<=500;j++) {
            float chosen=motor_td3_startup_handover_angle(4,hall,hall);
            assert(fabsf(difference(chosen,prev))<.0033f);prev=chosen;
        }
        assert(fabsf(difference(prev,hall))<2e-6f);
        assert(motor_td3_startup_handover_angle(4,hall,hall)>=0);
    }
    float integral=99;
    assert(motor_td3_startup_handover_pi(3,0,212,.003389f,1,&integral));
    assert(fabsf(integral+.003389f*212-1)<2e-6);
    assert(!motor_td3_startup_handover_pi(4,0,212,.003389f,1,&integral));
    fresh();unsigned run_steps=0;float first_iq=0,first_reset_iq=0;
    for(unsigned i=0;i<23000;i++) {
        now_us+=100;rtU.SpeedFd=788;
        float angle=rtDW.DiscreteTimeIntegrator1_DSTATE;
        rtU.theta=fmodf(angle+1.64f,6.28318530718f);
        float error=212;
        motor_td3_speedloop_pi_fast(error);
        if(i==10)assert(motor_td3_speedloop_pi_queue(2,1,.003389f,.00144f,3000000));
        FOC_Model_step();
        if(rtDW.Motor_state==4) {
            if(!run_steps)first_iq=rtDW.Merge1;
            if(rtM->Timing.TaskCounters.TID[1]==1 && first_reset_iq==0 && run_steps)first_reset_iq=rtDW.Merge1;
            ++run_steps;
        }
    }
    fprintf(stderr,"run_steps=%u first_iq=%.9g reset_iq=%.9g fault=%u\n",run_steps,first_iq,first_reset_iq,motor_td3_speedloop_pi_state.fault);
    assert(run_steps>500 && first_iq>.99f && first_iq<1.01f);
    assert(first_reset_iq>.99f && first_reset_iq<1.01f);
    assert(!motor_td3_speedloop_pi_state.fault);
    rtU.Motor_OnOff=0;now_us+=100;FOC_Model_step();
    assert(!motor_td3_startup_handover_state.closed_seen);
    printf("{\"passed\":true,\"handover_checks\":8,\"first_run_iq\":%.9g,\"reset_iq\":%.9g,\"hardware_accessed\":false}\n",first_iq,first_reset_iq);
}
