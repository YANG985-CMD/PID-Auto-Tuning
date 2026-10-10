/* No timer start, MOE enable, gain write or FOC step exists here. */
#include "motor_td3_speedloop_sample.h"
#include "motor_td3_g431_adapter.h"
#include "adc.h"
#include "FOC_Model.h"
#include <math.h>

extern uint8_t ADC_offset;
extern uint16_t IA_Offset,IB_Offset,IC_Offset,adc1_in1,adc1_in2,adc1_in3,adc_vbus,Vpoten;
extern float Ia,Ib,Ic,Vbus;
volatile uint32_t motor_td3_speedloop_sample_count;
volatile uint32_t motor_td3_speedloop_sample_errors;
static uint32_t offset_sum[3],offset_count;

static void invalid(void) {
    ++motor_td3_speedloop_sample_errors;
    Ia=Ib=Ic=Vbus=NAN;
    rtU.ia=rtU.ib=rtU.ic=rtU.v_bus=NAN;
    motor_td3_g431_fault_irq();
}

void motor_td3_speedloop_sample(void) {
    motor_td3_g431_disable();
    /* Poll complete injected SEQUENCES, not the first channel only.
     * Builder selects EOC_SEQ_CONV and disables external triggers. */
    if(HAL_ADCEx_InjectedStart(&hadc1)!=HAL_OK ||
       HAL_ADCEx_InjectedStart(&hadc2)!=HAL_OK ||
       HAL_ADCEx_InjectedPollForConversion(&hadc1,1)!=HAL_OK ||
       HAL_ADCEx_InjectedPollForConversion(&hadc2,1)!=HAL_OK) {
        invalid();return;
    }
    adc1_in1=(uint16_t)HAL_ADCEx_InjectedGetValue(&hadc1,ADC_INJECTED_RANK_1);
    adc1_in2=(uint16_t)HAL_ADCEx_InjectedGetValue(&hadc2,ADC_INJECTED_RANK_1);
    adc1_in3=(uint16_t)HAL_ADCEx_InjectedGetValue(&hadc1,ADC_INJECTED_RANK_2);
    if(adc1_in1>4095U || adc1_in2>4095U || adc1_in3>4095U) { invalid();return; }
    if(!ADC_offset) {
        offset_sum[0]+=adc1_in1;offset_sum[1]+=adc1_in2;offset_sum[2]+=adc1_in3;
        if(++offset_count==10U) {
            IA_Offset=(uint16_t)(offset_sum[0]/10U);
            IB_Offset=(uint16_t)(offset_sum[1]/10U);
            IC_Offset=(uint16_t)(offset_sum[2]/10U);
            ADC_offset=1;
        }
    }
    if(ADC_offset) {
        /* Preserve vendor's NOMINAL scale; this is not an ampere calibration. */
        Ia=((int32_t)adc1_in1-IA_Offset)*0.02197265625F;
        Ib=((int32_t)adc1_in2-IB_Offset)*0.02197265625F;
        Ic=((int32_t)adc1_in3-IC_Offset)*0.02197265625F;
        rtU.ia=Ia;rtU.ib=Ib;rtU.ic=Ic;
    } else {
        Ia=Ib=Ic=NAN;rtU.ia=rtU.ib=rtU.ic=NAN;
    }
    motor_td3_g431_poll();
    if(HAL_ADC_Start(&hadc1)!=HAL_OK || HAL_ADC_Start(&hadc2)!=HAL_OK ||
       HAL_ADC_PollForConversion(&hadc1,1)!=HAL_OK ||
       HAL_ADC_PollForConversion(&hadc2,1)!=HAL_OK) { invalid();return; }
    Vpoten=(uint16_t)HAL_ADC_GetValue(&hadc1);
    adc_vbus=(uint16_t)HAL_ADC_GetValue(&hadc2);
    if(adc_vbus>4095U) { invalid();return; }
    Vbus=adc_vbus*3.3F/4096.0F*26.0F;rtU.v_bus=Vbus;
    ++motor_td3_speedloop_sample_count;
    motor_td3_g431_adc_sample();
}
