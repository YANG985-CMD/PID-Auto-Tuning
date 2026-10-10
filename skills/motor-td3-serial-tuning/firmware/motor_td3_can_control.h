#ifndef MOTOR_TD3_CAN_CONTROL_H
#define MOTOR_TD3_CAN_CONTROL_H
#include "motor_td3_can.h"
#include "motor_td3_guard.h"
enum { TD3_CAN_PROTOCOL_FAULT=10,TD3_CAN_BOARD_FAULT=11,TD3_CAN_NOT_READY=12 };
typedef struct {
    void *user;
    void (*disable)(void *);
    int (*begin)(void *,float ref,float kp,float ki);
    int (*apply)(void *,float kp,float ki);
    /* Coherent snapshot of ACTUAL PI gains and physical PWM enabled feedback. */
    int (*snapshot)(void *,motor_td3_telemetry *);
} motor_td3_can_hooks;
typedef struct {
    motor_td3_guard guard;
    motor_td3_can_rx rx;
    motor_td3_can_command pending;
    motor_td3_can_hooks hooks;
    uint64_t boot,nonce;
    uint32_t wire_seq,telemetry_seq,max_age_us;
    const float *references;
    unsigned reference_count;
    uint16_t capabilities;
    int queued,rx_fault,hello_pending,owner,protocol_fault;
    char firmware[65],profile[65];
} motor_td3_can_control;
int motor_td3_can_control_init(motor_td3_can_control *,const motor_td3_limits *,
    const motor_td3_can_hooks *,uint64_t boot,const char *firmware,const char *profile,
    const float *verified_refs,unsigned ref_count,uint32_t max_age_us,uint16_t verified_capabilities);
/* Diagnostic-only identity/STOP service. No guessed limits or verified capabilities.
 * Permanently faulted; begin/apply callbacks can never be reached in this mode.
 * Missing sensor values must remain NaN: no training telemetry is fabricated. */
int motor_td3_can_control_init_locked(motor_td3_can_control *,const motor_td3_can_hooks *,
    uint64_t boot,const char *firmware,const char *profile);
/* Serialize RX queue access with the control task; no board callbacks in RX. */
int motor_td3_can_receive(motor_td3_can_control *,uint16_t id,int standard_data,
    const uint8_t frame[8],size_t dlc,uint64_t now_us);
/* Control task calls independently of CAN arrivals and host/trainer activity.
 * estop includes invalid Hall/current sensors and hardware fault inputs. */
void motor_td3_can_control_tick(motor_td3_can_control *,uint64_t now_us,int estop);
int motor_td3_can_make_hello(motor_td3_can_control *,uint8_t out[TD3_CAN_MAX_PACKET]);
int motor_td3_can_make_telemetry(motor_td3_can_control *,uint8_t out[TD3_CAN_MAX_PACKET]);
#endif
