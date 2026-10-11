#include "motor_td3_speedloop_hall.h"
#include <math.h>
int motor_td3_speedloop_hall_edge(motor_td3_speedloop_hall *s,uint64_t now,
                                 uint8_t code,float *rpm,float *theta_step) {
    static const int8_t index[8]={-1,5,3,4,1,0,2,-1};
    int difference;float direction,period;
    if(!s||!rpm||!theta_step||!code||code>6) return 0;
    if(!s->edges) {
        s->previous_us=now;s->previous_code=code;s->edges=1;
        *rpm=0;*theta_step=0;return 1;
    }
    if(now<=s->previous_us) return 0;
    difference=(index[code]-index[s->previous_code]+6)%6;
    if(difference!=1&&difference!=5) return 0;
    direction=difference==1?1.0f:-1.0f;
    period=(float)(now-s->previous_us);
    *rpm=direction*5000000.0f/period;
    *theta_step=direction*104.71975512f/period; /* electrical rad per 100 us */
    if(!isfinite(*rpm)||!isfinite(*theta_step)) return 0;
    s->previous_us=now;s->previous_code=code;++s->edges;
    return 1;
}
