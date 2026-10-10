#include "motor_td3_speedloop_pi_bind.h"
#include "FOC_Model.h"
#include "fuzzy_pid.h"
extern FuzzyPID_t fuzzy_speed_pid;
extern uint8_t Motor_state;
motor_td3_speedloop_pi motor_td3_speedloop_pi_state;
#ifndef MOTOR_TD3_SPEEDLOOP_PI_HOST
static uint32_t last_cycles,cycles_per_us;
static uint64_t elapsed_cycles;
#endif

void motor_td3_speedloop_pi_stop(void) {
#ifndef MOTOR_TD3_SPEEDLOOP_PI_HOST
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    TIM1->CCER=0;
#endif
    rtU.Motor_OnOff=0;Motor_state=0;
    if(!motor_td3_speedloop_pi_state.fault) motor_td3_speedloop_pi_state.fault=TD3_PI_OWNER;
}
void motor_td3_speedloop_pi_bind_init(void) {
    /* Mathematical envelope of the existing fuzzy rule tables; not proof that
     * arbitrary TD3 trajectories within it are safe or stable. */
    const motor_td3_speedloop_pi_domain d={TD3_SPEEDLOOP_KP-TD3_SPEEDLOOP_KP*.6f,TD3_SPEEDLOOP_KP+TD3_SPEEDLOOP_KP*.6f,
                                          TD3_SPEEDLOOP_KI*.5f,TD3_SPEEDLOOP_KI*1.5f};
    if(!motor_td3_speedloop_pi_init(&motor_td3_speedloop_pi_state,&d)) motor_td3_speedloop_pi_stop();
#ifndef MOTOR_TD3_SPEEDLOOP_PI_HOST
    cycles_per_us=SystemCoreClock/1000000U;elapsed_cycles=0;
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
    last_cycles=DWT->CYCCNT;
    if(!cycles_per_us||SystemCoreClock%1000000U) {
        motor_td3_speedloop_pi_state.fault=TD3_PI_CLOCK;motor_td3_speedloop_pi_stop();
    }
#endif
}
void motor_td3_speedloop_pi_fast(float error) {
    if(!isfinite(error)&&!motor_td3_speedloop_pi_state.fault) motor_td3_speedloop_pi_state.fault=TD3_PI_NUMERIC;
    if(motor_td3_speedloop_pi_state.fault) { motor_td3_speedloop_pi_stop();return; }
    if(motor_td3_speedloop_pi_state.mode==TD3_SPEEDLOOP_FUZZY) {
        FuzzyPID_Compute(&fuzzy_speed_pid,error);
        spd_kpki.spd_kp=fuzzy_speed_pid.Kp;spd_kpki.spd_ki=fuzzy_speed_pid.Ki;
    }
}
int motor_td3_speedloop_pi_model_boundary(float error,int reset,float *integral) {
    uint64_t now_us;
#ifdef MOTOR_TD3_SPEEDLOOP_PI_HOST
    now_us=motor_td3_speedloop_pi_host_time_us();
#else
    uint32_t cycles=DWT->CYCCNT,delta=cycles-last_cycles;last_cycles=cycles;
    if(!cycles_per_us||elapsed_cycles>UINT64_MAX-delta) {
        motor_td3_speedloop_pi_state.fault=TD3_PI_CLOCK;motor_td3_speedloop_pi_stop();return 0;
    }
    elapsed_cycles+=delta;now_us=elapsed_cycles/cycles_per_us;
#endif
    if(!motor_td3_speedloop_pi_boundary(&motor_td3_speedloop_pi_state,now_us,error,reset,
                                      integral,&spd_kpki.spd_kp,&spd_kpki.spd_ki)) {
        motor_td3_speedloop_pi_stop();return 0;
    }
    return 1;
}
int motor_td3_speedloop_pi_queue(unsigned mode,uint32_t seq,float kp,float ki,uint64_t deadline_us) {
    int ok;
#ifndef MOTOR_TD3_SPEEDLOOP_PI_HOST
    uint32_t mask=__get_PRIMASK();__disable_irq();
#endif
    ok=motor_td3_speedloop_pi_stage(&motor_td3_speedloop_pi_state,mode,seq,kp,ki,deadline_us);
    if(!ok) motor_td3_speedloop_pi_stop();
#ifndef MOTOR_TD3_SPEEDLOOP_PI_HOST
    __set_PRIMASK(mask);
#endif
    return ok;
}
