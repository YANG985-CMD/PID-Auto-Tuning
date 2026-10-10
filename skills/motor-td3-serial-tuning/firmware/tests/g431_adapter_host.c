/* Software-only hardware substitutes. NEVER compile into an MCU image. */
#include "motor_td3_g431_adapter.c"
TIM_TypeDef test_tim;
RCC_TypeDef test_rcc;
GPIO_TypeDef test_gpio;
FDCAN_HandleTypeDef hfdcan1;
ExtU rtU;
DW rtDW;
spd_kpki_type spd_kpki;
uint8_t Motor_state,ADC_offset;
float Ia,Ib,Ic,Vbus,HallSpeed,HallThetaAdd;
static FDCAN_RxHeaderTypeDef rxh;
static uint8_t rxd[8],sent[256][8];
static uint32_t sent_id[256],sent_count,available,freelevel,send_error;
static unsigned unlock_tick_countdown;
void test_unlock_hook(void) {
    if(unlock_tick_countdown && --unlock_tick_countdown==0) motor_td3_g431_tick_1ms();
}
void test_arm_unlock_tick(unsigned count) { unlock_tick_countdown=count; }
static FDCAN_FilterTypeDef filter;
static uint32_t global_filter[4];
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *h,FDCAN_FilterTypeDef *f) { (void)h;filter=*f;return HAL_OK; }
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *h,uint32_t a,uint32_t b,uint32_t c,uint32_t d) {
    (void)h;global_filter[0]=a;global_filter[1]=b;global_filter[2]=c;global_filter[3]=d;return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_ActivateNotification(FDCAN_HandleTypeDef *h,uint32_t f,uint32_t t) { (void)h;(void)f;(void)t;return HAL_OK; }
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *h) { (void)h;return HAL_OK; }
uint32_t HAL_FDCAN_GetRxFifoFillLevel(FDCAN_HandleTypeDef *h,uint32_t f) { (void)h;(void)f;return available; }
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *h,uint32_t f,FDCAN_RxHeaderTypeDef *o,uint8_t *b) {
    (void)h;(void)f;*o=rxh;memcpy(b,rxd,8);available=0;return HAL_OK;
}
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(FDCAN_HandleTypeDef *h) { (void)h;return freelevel; }
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *h,FDCAN_TxHeaderTypeDef *t,uint8_t *b) {
    (void)h;if(send_error) return 1;
    if(sent_count<256) { sent_id[sent_count]=t->Identifier;memcpy(sent[sent_count++],b,8); }
    return HAL_OK;
}
void test_reset(void) {
    memset(&test_tim,0,sizeof(test_tim));memset(&test_rcc,0,sizeof(test_rcc));memset(&test_gpio,0,sizeof(test_gpio));
    memset(&endpoint,0,sizeof(endpoint));memset(&rtU,0,sizeof(rtU));memset(&rtDW,0,sizeof(rtDW));
    Motor_state=ADC_offset=0;Ia=Ib=Ic=Vbus=HallSpeed=HallThetaAdd=0;
    spd_kpki.spd_kp=.003389f;spd_kpki.spd_ki=.00144f;
    ring_write=ring_read=irq_fault=initialized=adc_samples=hall_bad=0;
    now_us=main_seen_us=adc_seen_us=tx_started_us=diag_due_us=0;
    tx_length=tx_index=diag_index=tx_transfer=endpoint_ready=0;
    motor_td3_g431_debugger_boot_token=0;sent_count=available=send_error=0;freelevel=3;
    unlock_tick_countdown=0;
    test_rcc.APB2ENR=RCC_APB2ENR_TIM1EN;motor_td3_g431_init();
}
void test_boot(uint64_t boot) { motor_td3_g431_debugger_boot_token=boot;motor_td3_g431_poll(); }
void test_feed(const uint8_t *f,int bad_format) {
    memcpy(rxd,f,8);memset(&rxh,0,sizeof(rxh));rxh.Identifier=0x620;
    rxh.IdType=FDCAN_STANDARD_ID;rxh.RxFrameType=FDCAN_DATA_FRAME;rxh.FDFormat=FDCAN_CLASSIC_CAN;
    rxh.DataLength=FDCAN_DLC_BYTES_8;rxh.BitRateSwitch=FDCAN_BRS_OFF;
    if(bad_format) rxh.FDFormat=99;
    available=1;HAL_FDCAN_RxFifo0Callback(&hfdcan1,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
}
void test_poll(void) { motor_td3_g431_poll(); }
void test_ticks(unsigned count) { while(count--) motor_td3_g431_tick_1ms(); }
unsigned test_sent(unsigned index,uint8_t *out) { if(index>=sent_count)return 0;memcpy(out,sent[index],8);return sent_id[index]; }
unsigned test_count(void) { return sent_count; }
unsigned test_fault(void) { return irq_fault; }
unsigned test_guard_fault(void) { return endpoint.guard.fault; }
unsigned test_filter_ok(void) {
    return filter.IdType==FDCAN_STANDARD_ID&&filter.FilterID1==0x620&&filter.FilterID2==0x7ff&&
        global_filter[0]==FDCAN_REJECT&&global_filter[1]==FDCAN_REJECT&&
        global_filter[2]==FDCAN_REJECT_REMOTE&&global_filter[3]==FDCAN_REJECT_REMOTE;
}
void test_software_outputs_on(void) { test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TD3_G431_PHASE_MASK|TIM_CCER_CC4E;Motor_state=255;rtU.Motor_OnOff=1; }
unsigned test_off(void) { return !(test_tim.BDTR&TIM_BDTR_MOE)&&!(test_tim.CCER&TD3_G431_PHASE_MASK)&&!Motor_state&&rtU.Motor_OnOff==0; }
unsigned test_ch4(void) { return (test_tim.CCER&TIM_CCER_CC4E)!=0; }
float test_kp(void) { return spd_kpki.spd_kp; }
float test_ki(void) { return spd_kpki.spd_ki; }
int test_telemetry(void) { uint8_t out[192];return motor_td3_can_make_telemetry(&endpoint,out); }
void test_freelevel(unsigned count) { freelevel=count; }
void test_tx_error(void) { send_error=1; }
void test_can_error(void) { HAL_FDCAN_ErrorStatusCallback(&hfdcan1,FDCAN_IT_BUS_OFF); }
void test_break_flags(unsigned flags) { test_tim.SR=flags; }
void test_timer_clock(unsigned on) { test_rcc.APB2ENR=on?RCC_APB2ENR_TIM1EN:0; }
void test_hall_pins(unsigned idr) { test_gpio.IDR=idr; }
