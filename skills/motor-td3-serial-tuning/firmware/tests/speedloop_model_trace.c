/* Baseline parity trace: the same actual model/fuzzy sources with and without
 * the gain owner patch. Synthetic feedback; no claim about plant performance. */
#include "FOC_Model.h"
#include "fuzzy_pid.h"
#include "motor_td3_speedloop_pi_bind.h"
#include <stdio.h>
FuzzyPID_t fuzzy_speed_pid;
uint8_t Motor_state;
static uint64_t now_us;
uint64_t motor_td3_speedloop_pi_host_time_us(void) { return now_us; }
int main(void) {
    FOC_Model_initialize();FuzzyPID_Init(&fuzzy_speed_pid,TD3_SPEEDLOOP_KP,TD3_SPEEDLOOP_KI,0,500,100);
#ifndef SPEEDLOOP_UNPATCHED_TRACE
    motor_td3_speedloop_pi_bind_init();
#endif
    rtU.v_bus=24;rtU.SpeedRef=1000;
    for(unsigned i=0;i<2000;++i) {
        float error=(float)((int)(i*17%1601)-800);
        now_us+=100;rtU.SpeedFd=1000-error;
#ifdef SPEEDLOOP_UNPATCHED_TRACE
        FuzzyPID_Compute(&fuzzy_speed_pid,error);
        spd_kpki.spd_kp=fuzzy_speed_pid.Kp;spd_kpki.spd_ki=fuzzy_speed_pid.Ki;
#else
        motor_td3_speedloop_pi_fast(error);
#endif
        FOC_Model_step();
        printf("%.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %u\n",
            spd_kpki.spd_kp,spd_kpki.spd_ki,rtDW.Integrator_DSTATE_h,rtDW.Integrator_PREV_U,
            rtDW.Saturation,rtY.tABC[0],rtY.tABC[1],rtY.tABC[2],rtM->Timing.clockTick1);
    }
    return 0;
}
