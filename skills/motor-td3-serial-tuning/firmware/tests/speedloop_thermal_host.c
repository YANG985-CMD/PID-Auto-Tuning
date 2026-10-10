/* Real glue, software-only driver variables; NEVER compile into MCU image. */
#include "motor_td3_speedloop_thermal.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
uint8_t ADC_offset;
uint16_t adc1_in1,adc1_in2,adc1_in3;
float HallSpeed;
volatile uint32_t motor_td3_speedloop_sample_count,motor_td3_speedloop_sample_errors;
static unsigned off_calls,output_active;
void motor_td3_g431_disable(void) { ++off_calls;output_active=0; }
int main(void) {
    unsigned i,n;
    output_active=1;motor_td3_speedloop_thermal_init();
    assert(!output_active&&off_calls&&motor_td3_speedloop_thermal_state.fault==TD3_FEED_CALIBRATION);
    ADC_offset=1;adc1_in1=2021;adc1_in2=2029;adc1_in3=2025;
    for(i=0;i<30;++i) {
        motor_td3_speedloop_thermal_tick_1ms();
        ++motor_td3_speedloop_sample_count;output_active=1;
        motor_td3_speedloop_thermal_sample();motor_td3_speedloop_thermal_poll();assert(!output_active);
    }
    assert(motor_td3_speedloop_thermal_state.fault==TD3_FEED_CALIBRATION);
    assert(!motor_td3_speedloop_thermal_state.guard.has_window);n=off_calls;
    motor_td3_speedloop_thermal_init();assert(off_calls>n&&!output_active);
    assert(motor_td3_speedloop_thermal_state.fault==TD3_FEED_CALIBRATION);
    printf("{\"test_groups\":3,\"passed\":true,\"hardware_accessed\":false,\"calibration_absence_latched\":true}\n");
    return 0;
}
