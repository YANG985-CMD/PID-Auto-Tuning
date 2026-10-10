/* Software substitutes for diagnostic sampling. Never include in MCU builds. */
#include "motor_td3_speedloop_sample.c"
#include <string.h>
ADC_HandleTypeDef hadc1,hadc2;
ExtU rtU;
uint8_t ADC_offset;
uint16_t IA_Offset,IB_Offset,IC_Offset,adc1_in1,adc1_in2,adc1_in3,adc_vbus,Vpoten;
float Ia,Ib,Ic,Vbus;
static unsigned calls,fail_at,faults,disable_calls,polls,fresh;
static uint32_t raw[3],bus;
static int status(void) { return ++calls==fail_at?1:HAL_OK; }
int HAL_ADCEx_InjectedStart(ADC_HandleTypeDef *h) { (void)h;return status(); }
int HAL_ADCEx_InjectedPollForConversion(ADC_HandleTypeDef *h,uint32_t ms) { (void)h;(void)ms;return status(); }
uint32_t HAL_ADCEx_InjectedGetValue(ADC_HandleTypeDef *h,uint32_t rank) {
    return h==&hadc2?raw[1]:(rank==ADC_INJECTED_RANK_1?raw[0]:raw[2]);
}
int HAL_ADC_Start(ADC_HandleTypeDef *h) { (void)h;return status(); }
int HAL_ADC_PollForConversion(ADC_HandleTypeDef *h,uint32_t ms) { (void)h;(void)ms;return status(); }
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef *h) { return h==&hadc2?bus:0; }
void motor_td3_g431_disable(void) { ++disable_calls; }
void motor_td3_g431_fault_irq(void) { ++faults;motor_td3_g431_disable(); }
void motor_td3_g431_poll(void) { ++polls; }
void motor_td3_g431_adc_sample(void) { ++fresh;motor_td3_g431_disable(); }
void test_reset(void) {
    memset(&rtU,0,sizeof(rtU));memset(offset_sum,0,sizeof(offset_sum));
    offset_count=ADC_offset=0;motor_td3_speedloop_sample_count=motor_td3_speedloop_sample_errors=0;
    IA_Offset=IB_Offset=IC_Offset=0;Ia=Ib=Ic=Vbus=0;
    calls=fail_at=faults=disable_calls=polls=fresh=0;
    raw[0]=2021;raw[1]=2029;raw[2]=2025;bus=1150;
}
void test_sample(unsigned fail) { calls=0;fail_at=fail;motor_td3_speedloop_sample(); }
void test_raw(unsigned a,unsigned b,unsigned c,unsigned v) { raw[0]=a;raw[1]=b;raw[2]=c;bus=v; }
unsigned test_count(void) { return motor_td3_speedloop_sample_count; }
unsigned test_errors(void) { return motor_td3_speedloop_sample_errors; }
unsigned test_faults(void) { return faults; }
unsigned test_fresh(void) { return fresh; }
unsigned test_disabled(void) { return disable_calls; }
unsigned test_offset(unsigned i) { return i==0?IA_Offset:i==1?IB_Offset:IC_Offset; }
unsigned test_calibrated(void) { return ADC_offset; }
float test_current(unsigned i) { return i==0?Ia:i==1?Ib:Ic; }
float test_bus(void) { return Vbus; }
