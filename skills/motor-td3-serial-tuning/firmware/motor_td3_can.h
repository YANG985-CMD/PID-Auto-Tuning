#ifndef MOTOR_TD3_CAN_H
#define MOTOR_TD3_CAN_H
#include "motor_td3_protocol.h"
#define TD3_CAN_MAX_PACKET 192U
#define TD3_CAN_REQUEST_ID 0x620U
#define TD3_CAN_RESPONSE_ID 0x621U
#define TD3_CAN_FRAGMENT_TIMEOUT_US 50000U
#define TD3_CAN_CAPABILITIES_ALL 63U
typedef struct {
    uint8_t bytes[TD3_CAN_MAX_PACKET],active,transfer,index,length;
    uint16_t used;
    uint64_t started_us,last_us;
} motor_td3_can_rx;
typedef struct {
    uint64_t nonce,boot,expires_us;
    uint32_t wire_seq;
    motor_td3_command command;
} motor_td3_can_command;
/* feed: -1 malformed/expired, 0 incomplete, 1 complete. State owns packet.
 * ISR must only enqueue; control task handles guard and actual PWM-off. */
int motor_td3_can_feed(motor_td3_can_rx *,const uint8_t frame[8],size_t dlc,uint64_t now_us);
int motor_td3_can_fragment(const uint8_t *,size_t length,uint8_t transfer,unsigned index,uint8_t out[8]);
int motor_td3_can_decode(const uint8_t *,size_t length,motor_td3_can_command *);
int motor_td3_can_hello(uint8_t out[TD3_CAN_MAX_PACKET],uint64_t nonce,uint64_t boot,
                        uint16_t capabilities,const char *firmware,const char *profile);
int motor_td3_can_telemetry(uint8_t out[TD3_CAN_MAX_PACKET],uint64_t nonce,uint64_t boot,
                           const motor_td3_telemetry *);
#endif
