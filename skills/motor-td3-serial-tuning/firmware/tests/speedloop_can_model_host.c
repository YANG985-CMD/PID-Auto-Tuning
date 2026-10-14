/* Software board hooks, real protocol and user's actual generated model. */
#include "FOC_Model.h"
#include "fuzzy_pid.h"
#include "motor_td3_speedloop_pi_bind.h"
#include "motor_td3_speedloop_can.h"
#include <string.h>
FuzzyPID_t fuzzy_speed_pid;
uint8_t Motor_state;
static uint64_t now_us;
static int enabled,locked;
static float current,temperature;
static motor_td3_can_control endpoint;
static motor_td3_speedloop_can link;
uint64_t motor_td3_speedloop_pi_host_time_us(void) { return now_us; }
static void disable(void *p) { (void)p;enabled=0;rtU.Motor_OnOff=0;Motor_state=0; }
static int begin(void *p,float ref,float kp,float ki) {
    (void)p;(void)kp;(void)ki;enabled=1;rtU.SpeedRef=ref;rtU.Motor_OnOff=1;Motor_state=1;return 1;
}
static int snapshot(void *p,motor_td3_telemetry *t) {
    (void)p;memset(t,0,sizeof(*t));t->enabled=enabled;t->t_us=now_us;
    t->kp=spd_kpki.spd_kp;t->ki=spd_kpki.spd_ki;t->speed_ref=rtU.SpeedRef;t->speed=rtU.SpeedFd;
    t->error_history=link.previous_error;t->integral_output=rtDW.Integrator_DSTATE_h;
    t->current=current;t->vbus=rtU.v_bus;t->temperature_c=temperature;
    t->elapsed_ms=endpoint.guard.enabled?(float)(now_us-endpoint.guard.started_us)/1000:0;
    return 1;
}
int test_init(int inhibit) {
    /* Synthetic fixture limits and temperature are never a board profile. */
    const motor_td3_limits limits={.0013556f,.0054224f,.00072f,.00216f,.001f,.0005f,
        .003389f,.00144f,8,2000,18,30,70,500000,100000,1000000,20};
    static const float refs[]={500};
    const motor_td3_can_hooks board={0,disable,begin,0,snapshot};motor_td3_can_hooks hooks;
    memset(&rtDW,0,sizeof(rtDW));memset(&rtU,0,sizeof(rtU));memset(&rtY,0,sizeof(rtY));
    memset(rtM,0,sizeof(*rtM));now_us=0;enabled=0;locked=inhibit;current=0;temperature=locked?NAN:25;
    spd_kpki.spd_kp=TD3_SPEEDLOOP_KP;spd_kpki.spd_ki=TD3_SPEEDLOOP_KI;
    FOC_Model_initialize();FuzzyPID_Init(&fuzzy_speed_pid,TD3_SPEEDLOOP_KP,TD3_SPEEDLOOP_KI,0,500,100);
    motor_td3_speedloop_pi_bind_init();rtU.v_bus=24;rtU.SpeedRef=500;
    if(!motor_td3_speedloop_can_attach(&link,&endpoint,&board,&hooks)) return 0;
    return locked?motor_td3_can_control_init_locked(&endpoint,&hooks,0x1122334455667788ULL,
           "speedloop-can-test","speedloop-can-test"):
        motor_td3_can_control_init(&endpoint,&limits,&hooks,0x1122334455667788ULL,
           "speedloop-can-test","speedloop-can-test",refs,1,50000,TD3_CAN_CAPABILITIES_ALL);
}
int test_feed(const uint8_t f[8]) { return motor_td3_can_receive(&endpoint,TD3_CAN_REQUEST_ID,1,f,8,now_us); }
void test_base_tick(void) { now_us+=100;motor_td3_speedloop_pi_fast(rtU.SpeedRef-rtU.SpeedFd);FOC_Model_step(); }
void test_reset(int yes) { rtDW.SpeedReset=yes?1:0;rtDW.Integrator_PrevResetState=0; }
void test_sensor(float amps,float temp) { current=amps;temperature=temp; }
int test_hello(uint8_t out[TD3_CAN_MAX_PACKET]) { return motor_td3_can_make_hello(&endpoint,out); }
int test_telemetry(uint8_t out[TD3_CAN_MAX_PACKET]) { return motor_td3_can_make_telemetry(&endpoint,out); }
uint64_t test_time(void) { return now_us; }
uint64_t test_apply_time(void) { return motor_td3_speedloop_pi_state.applied_us; }
unsigned test_applied(void) { return endpoint.guard.applied_seq; }
unsigned test_pi_sequence(void) { return motor_td3_speedloop_pi_state.applied_seq; }
unsigned test_fault(void) { return (unsigned)endpoint.guard.fault; }
int test_enabled(void) { return enabled; }
float test_kp(void) { return spd_kpki.spd_kp; }
float test_ki(void) { return spd_kpki.spd_ki; }
float test_before(void) { return motor_td3_speedloop_pi_state.sum_before; }
float test_after(void) { return motor_td3_speedloop_pi_state.sum_after; }
