/* SOFTWARE-ONLY fixture. No HAL, GPIO, serial, CAN driver or physical motor. */
#include "../motor_td3_can_control.h"
#include <string.h>
static motor_td3_can_control ctx;
static motor_td3_telemetry physical;
static int apply_mode;
static void disable(void *u) { (void)u; physical.enabled=0; physical.current=0; }
static int begin(void *u,float ref,float kp,float ki) {
    (void)u; physical.enabled=1; physical.speed_ref=ref; physical.speed=ref*.8f;
    physical.kp=kp; physical.ki=ki; physical.current=1; physical.error_history=ref-physical.speed; return 1;
}
static int apply(void *u,float kp,float ki) {
    (void)u; if(apply_mode==1) return 0;
    if(apply_mode!=2) { physical.kp=kp; physical.ki=ki; } return 1;
}
static int snap(void *u,motor_td3_telemetry *out) { (void)u; *out=physical; return 1; }
int test_init(uint64_t boot) {
    static const float refs[]={500,800,1100};
    const motor_td3_limits limits={.0025f,.0043f,.0008f,.0022f,.00008f,.00008f,.003389f,.00144f,
        4,1800,20,28,75,5000000U,5000000U,4000000U,30};
    const motor_td3_can_hooks hooks={0,disable,begin,apply,snap};
    memset(&physical,0,sizeof(physical)); physical.kp=limits.kp_baseline; physical.ki=limits.ki_baseline;
    physical.vbus=24; physical.temperature_c=30; apply_mode=0;
    return motor_td3_can_control_init(&ctx,&limits,&hooks,boot,"software-can-peer-v1","test-can-profile-v1",refs,3,300000U,63);
}
int test_feed(const uint8_t *f,unsigned dlc,uint64_t now) { return motor_td3_can_receive(&ctx,0x620,1,f,dlc,now); }
void test_tick(uint64_t now) { physical.elapsed_ms=(float)(now-ctx.guard.started_us)/1000; motor_td3_can_control_tick(&ctx,now,0); }
int test_hello(uint8_t *out) { return motor_td3_can_make_hello(&ctx,out); }
int test_telemetry(uint8_t *out) { return motor_td3_can_make_telemetry(&ctx,out); }
int test_fragment(const uint8_t *p,unsigned len,unsigned tag,unsigned idx,uint8_t *out) { return motor_td3_can_fragment(p,len,(uint8_t)tag,idx,out); }
int test_decode(const uint8_t *p,unsigned len) { motor_td3_can_command out; return motor_td3_can_decode(p,len,&out); }
int test_enabled(void) { return physical.enabled; }
int test_fault(void) { return ctx.guard.fault; }
uint32_t test_applied(void) { return ctx.guard.applied_seq; }
uint32_t test_wireseq(void) { return ctx.wire_seq; }
uint64_t test_deadline(void) { return ctx.guard.deadline_us; }
float test_kp(void) { return physical.kp; }
void test_apply_mode(int mode) { apply_mode=mode; }
void test_current(float current) { physical.current=current; }
void test_link_timeout(uint32_t us) { ctx.guard.limits.link_timeout_us=us; }
