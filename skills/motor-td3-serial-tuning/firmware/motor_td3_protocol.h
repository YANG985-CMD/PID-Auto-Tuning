#ifndef MOTOR_TD3_PROTOCOL_H
#define MOTOR_TD3_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
enum { TD3_HELLO=1,TD3_BEGIN=2,TD3_GAINS=3,TD3_STOP=4 };
typedef struct {
    int type;
    char profile_id[96];
    uint32_t command_seq,lease_ms;
    float kp,ki,speed_ref;
} motor_td3_command;
typedef struct {
    uint64_t t_us,t_apply_us;
    uint32_t seq,applied_seq,fault;
    int enabled;
    float speed_ref,speed,error_history,integral_output,current,vbus,temperature_c,kp,ki,elapsed_ms;
} motor_td3_telemetry;
/* Full frame includes JSON*CRC32\n. No heap; <=1024 bytes command.
 * Strings are restricted ASCII identifiers. Unknown/repeated fields rejected.
 * MCU RX must discard an overlong frame through LF, then stop/latch fault. */
int motor_td3_decode(const char *frame,size_t length,motor_td3_command *command);
int motor_td3_encode_hello(char *out,size_t capacity,const char *firmware_id,const char *profile_id,const char *boot_id);
int motor_td3_encode_telemetry(char *out,size_t capacity,const char *boot_id,const motor_td3_telemetry *telemetry);
#endif
