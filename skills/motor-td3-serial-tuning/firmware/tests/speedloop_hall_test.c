#include "motor_td3_speedloop_hall.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
int main(void) {
    motor_td3_speedloop_hall s={0};float rpm,step;
    assert(motor_td3_speedloop_hall_edge(&s,100000,5,&rpm,&step));
    assert(rpm==0&&step==0);
    assert(motor_td3_speedloop_hall_edge(&s,200000,4,&rpm,&step));
    assert(fabsf(rpm-50)<.001f); /* 100ms: several 16-bit TIM4 wraps. */
    assert(motor_td3_speedloop_hall_edge(&s,205000,6,&rpm,&step));
    assert(fabsf(rpm-1000)<.001f&&step>0);
    assert(motor_td3_speedloop_hall_edge(&s,210000,4,&rpm,&step));
    assert(fabsf(rpm+1000)<.001f&&step<0);
    assert(!motor_td3_speedloop_hall_edge(&s,211000,4,&rpm,&step));
    assert(!motor_td3_speedloop_hall_edge(&s,211000,2,&rpm,&step));
    assert(!motor_td3_speedloop_hall_edge(&s,210000,6,&rpm,&step));
    assert(!motor_td3_speedloop_hall_edge(&s,211000,0,&rpm,&step));
    assert(motor_td3_speedloop_hall_edge(&s,210500,6,&rpm,&step));
    assert(fabsf(rpm-10000)<.01f); /* High speed reaches guard, never clipped. */
    s=(motor_td3_speedloop_hall){0};
    assert(motor_td3_speedloop_hall_edge(&s,0x100000010ULL,5,&rpm,&step));
    assert(motor_td3_speedloop_hall_edge(&s,0x100001398ULL,4,&rpm,&step));
    assert(fabsf(rpm-1000)<.001f); /* Full-width timestamp beyond 32 bits. */
    puts("{\"passed\":true,\"checks\":10,\"hardware_accessed\":false}");
}
