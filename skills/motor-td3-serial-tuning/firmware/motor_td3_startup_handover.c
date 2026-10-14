#include "motor_td3_startup_handover.h"
#include <math.h>
#include <string.h>
motor_td3_startup_handover motor_td3_startup_handover_state;
static float wrap(float x) {
    x=fmodf(x,6.28318530718f);if(x<0)x+=6.28318530718f;return x;
}
void motor_td3_startup_handover_reset(void) {
    memset(&motor_td3_startup_handover_state,0,sizeof(motor_td3_startup_handover_state));
}
float motor_td3_startup_handover_angle(unsigned stage,float chosen,float hall) {
    motor_td3_startup_handover *s=&motor_td3_startup_handover_state;
    if(stage!=3U && stage!=4U) {motor_td3_startup_handover_reset();return chosen;}
    if(stage==3U) {
        s->open_seen=1;s->last_open_angle=wrap(chosen);s->selected_angle=s->last_open_angle;
        return chosen;
    }
    if(!s->open_seen)return chosen;
    if(!s->closed_seen) {
        s->initial_offset=wrap(s->last_open_angle-hall+3.14159265359f)-3.14159265359f;
        s->closed_seen=1;s->closed_steps=0;
    }
    /* Exactly 500 actual 100us FOC calls = 50ms. No angle-source snap.
     * This is a commissioning choice, not a stability or safety guarantee. */
    float fraction=(float)s->closed_steps/500.0f;
    if(s->closed_steps<500U)++s->closed_steps;
    s->selected_angle=wrap(hall+s->initial_offset*(1.0f-fraction));
    return s->selected_angle;
}
int motor_td3_startup_handover_pi(unsigned stage,int reset,float error,float kp,
                                 float iq,float *integral) {
    if(!integral || !isfinite(error) || !isfinite(kp) || !isfinite(iq))return 0;
    /* Track the 1A open-stage command instead of integrating an unused PI.
     * On the first generated Run-stage reset, track the previously selected
     * command once. Subsequent PI integration/anti-windup is unchanged. */
    if(stage==3U || (stage==4U && reset && motor_td3_startup_handover_state.closed_seen)) {
        float target=stage==3U?1.0f:iq;
        if(target>3.0f)target=3.0f;
        if(target< -3.0f)target= -3.0f;
        *integral=target-kp*error;return 1;
    }
    return 0;
}
