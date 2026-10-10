/* Software-only test driver. Never link into a motor MCU application. */
#include "motor_td3_thermal_can.h"
#include <assert.h>
#include <string.h>
static unsigned off_calls;
static void off(void *u) { (void)u;++off_calls; }
int test_heat_case(uint8_t out[TD3_THERMAL_CAN_BYTES],unsigned which) {
    motor_td3_thermal_feed f={0},before;
    motor_td3_current_calibration c={{2048,2048,2048},{.01f,.01f,.01f},
        {1000,1000,1000},{3000,3000,3000},1};
    motor_td3_thermal_limits l={{1,1,1},{5,5,5},{.5f,.5f,.5f},10,2,10000,2,1000,1000000,100000,1};
    motor_td3_thermal_seed seed={{0,0,0},0,0,1};
    motor_td3_thermal_sample s={0};unsigned i,previous;uint64_t now=0;
    if(which==0) c.calibrated=0;
    if(which==1) seed.known=0;
    if(which==3) l.budget_a2s[0]=.005f;
    if(which==5) seed.used_a2s[0]=1;
    if(which==6) seed.used_a2s[1]=-1;
    (void)motor_td3_thermal_feed_init(&f,&c,&l,&seed,0,off,0);
    if(which==2||which==3||which==4||which==7||which==8) {
        for(i=1;i<=2;++i) {
            s.sequence=i;s.capture_us=i*5000;s.valid=1;s.speed_rpm=100;s.output_active=1;
            s.raw_adc[0]=(uint16_t)(which==7?2700:which==8?2048:2200);
            s.raw_adc[1]=s.raw_adc[2]=2048;
            (void)motor_td3_thermal_feed_sample(&f,&s,s.capture_us);now=s.capture_us;
        }
    }
    if(which==4) { now=17001;(void)motor_td3_thermal_feed_check(&f,now); }
    before=f;previous=off_calls;
    i=(unsigned)motor_td3_thermal_can_packet(out,&f,7,0x1234567812345678ULL,1,now);
    assert(memcmp(&before,&f,sizeof(f))==0&&previous==off_calls);
    return (int)i;
}
int test_heat_arguments(void) {
    uint8_t out[TD3_THERMAL_CAN_BYTES];motor_td3_thermal_feed f={0};
    return !motor_td3_thermal_can_packet(0,&f,1,1,1,0)&&
        !motor_td3_thermal_can_packet(out,0,1,1,1,0)&&
        !motor_td3_thermal_can_packet(out,&f,0,1,1,0)&&
        !motor_td3_thermal_can_packet(out,&f,1,0,1,0)&&
        !motor_td3_thermal_can_packet(out,&f,1,1,0,0);
}
