/* Host-only verification of the scalar fields actually journaled by v27. */
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
static float previous_error;
uint64_t motor_td3_speedloop_pi_host_time_us(void) { return now_us; }
static int service(void *u,uint64_t now,float error,int reset,float *integral) {
    (void)u;
    int ok=motor_td3_speedloop_pi_boundary(&motor_td3_speedloop_pi_state,now,error,reset,
        integral,&spd_kpki.spd_kp,&spd_kpki.spd_ki);
    previous_error=error; /* Same publication order as the CAN binding. */
    return ok;
}
static float clamp(float x) { return x>3?3:x< -3?-3:x; }
int main(void) {
    memset(&rtDW,0,sizeof(rtDW));memset(&rtU,0,sizeof(rtU));memset(&rtY,0,sizeof(rtY));memset(rtM,0,sizeof(*rtM));
    FOC_Model_initialize();FuzzyPID_Init(&fuzzy_speed_pid,.003389f,.00144f,0,500,100);
    motor_td3_speedloop_pi_bind_init();assert(motor_td3_speedloop_pi_set_service(service,0));
    rtU.Motor_OnOff=1;rtU.v_bus=24;rtU.SpeedRef=1000;
    unsigned cases=0,different_instantaneous_error_cases=0;float maximum_error=0,wrong_error=0;
    const float gains[]={.003389f,.00325344f,.003121269f,.002989098f,.002856927f,.002989098f,.003121269f,.00325344f,.003389f,.00352456f,.00366012f,.00352456f};
    uint32_t seq=0;
    for(unsigned i=0;i<60000;i++) {
        now_us+=100;
        rtU.SpeedFd=1000+120*sinf(i*.013f)+31*cosf(i*.071f);
        if(i%100==10)assert(motor_td3_speedloop_pi_queue(2,++seq,gains[(i/100)%12],.00144f,now_us+200000));
        motor_td3_speedloop_pi_fast(rtU.SpeedRef-rtU.SpeedFd);FOC_Model_step();
        if(i<25000 || rtDW.Motor_state!=4)continue;
        float reconstructed=clamp(spd_kpki.spd_kp*previous_error+rtDW.Integrator_DSTATE_h);
        float diff=fabsf(reconstructed-rtDW.Saturation);if(diff>maximum_error)maximum_error=diff;
        assert(diff<1e-7f);
        assert(fabsf(rtDW.Merge1-rtDW.Saturation)<1e-7f);
        float wrong=clamp(spd_kpki.spd_kp*(rtU.SpeedRef-rtU.SpeedFd)+rtDW.Integrator_DSTATE_h);
        diff=fabsf(wrong-rtDW.Saturation);if(diff>wrong_error)wrong_error=diff;
        if(diff>1e-5f)different_instantaneous_error_cases++;
        cases++;
    }
    assert(cases==35000 && !motor_td3_speedloop_pi_state.fault);
    assert(different_instantaneous_error_cases>20000 && wrong_error>.005f);
    printf("{\"passed\":true,\"actual_generated_model_cases\":%u,\"maximum_reconstruction_error\":%.9g,\"instantaneous_error_mismatch_cases\":%u,\"instantaneous_error_maximum_mismatch\":%.9g,\"uses_previous_PI_error\":true,\"synthetic_test_inputs\":true,\"motor_response_measured\":false,\"hardware_accessed\":false}\n",cases,maximum_error,different_instantaneous_error_cases,wrong_error);
}
