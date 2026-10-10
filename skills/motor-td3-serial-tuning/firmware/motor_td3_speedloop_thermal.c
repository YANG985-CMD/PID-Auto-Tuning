#include "motor_td3_speedloop_thermal.h"
#include "motor_td3_speedloop_sample.h"
#include "motor_td3_g431_adapter.h"
#include "main.h"

#if !defined(MOTOR_TD3_SPEEDLOOP_DIAGNOSTIC) || !defined(MOTOR_TD3_SPEEDLOOP_WATCHDOG)
#error Thermal audit glue requires the motion-inhibited SpeedLoop watchdog build
#endif
extern uint8_t ADC_offset;
extern uint16_t adc1_in1,adc1_in2,adc1_in3;
extern float HallSpeed;
motor_td3_thermal_feed motor_td3_speedloop_thermal_state;
static volatile uint64_t clock_us;
static uint32_t previous_sample_count;
static uint64_t source_sequence;
/* Intentionally missing engineering records. Never replace them with mock data. */
static const motor_td3_current_calibration calibration={0};
static const motor_td3_thermal_limits limits={0};
static const motor_td3_thermal_seed seed={0};
static uint64_t now(void) {
    uint32_t mask=__get_PRIMASK();uint64_t n;
    __disable_irq();n=clock_us;__set_PRIMASK(mask);return n;
}
static void disable(void *user) { (void)user;motor_td3_g431_disable(); }
int motor_td3_speedloop_thermal_packet(uint8_t out[TD3_THERMAL_CAN_BYTES],
    uint64_t nonce,uint64_t boot,uint32_t seq) {
    return motor_td3_thermal_can_packet(out,&motor_td3_speedloop_thermal_state,nonce,boot,seq,now());
}
void motor_td3_speedloop_thermal_tick_1ms(void) { clock_us+=1000U; }
void motor_td3_speedloop_thermal_init(void) {
    (void)motor_td3_thermal_feed_init(&motor_td3_speedloop_thermal_state,&calibration,&limits,&seed,now(),disable,0);
}
void motor_td3_speedloop_thermal_poll(void) {
    (void)motor_td3_thermal_feed_check(&motor_td3_speedloop_thermal_state,now());
}
void motor_td3_speedloop_thermal_sample(void) {
    motor_td3_thermal_sample s={0};uint32_t count=motor_td3_speedloop_sample_count;
    s.capture_us=now();s.sequence=++source_sequence;
    s.raw_adc[0]=adc1_in1;s.raw_adc[1]=adc1_in2;s.raw_adc[2]=adc1_in3;s.speed_rpm=HallSpeed;
    s.valid=ADC_offset&&motor_td3_speedloop_sample_errors==0&&count==previous_sample_count+1U;
    previous_sample_count=count;
    s.output_active=0; /* builder removes ALL PWM starts; separate locked disable runs */
    (void)motor_td3_thermal_feed_sample(&motor_td3_speedloop_thermal_state,&s,s.capture_us);
}
