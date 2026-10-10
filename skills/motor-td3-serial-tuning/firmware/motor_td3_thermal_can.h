#ifndef MOTOR_TD3_THERMAL_CAN_H
#define MOTOR_TD3_THERMAL_CAN_H
#include "motor_td3_thermal_feed.h"
#define TD3_THERMAL_CAN_ID 0x626U
#define TD3_THERMAL_CAN_BYTES 144U
enum { TD3_HEAT_CALIBRATED=1, TD3_HEAT_LIMITS=2, TD3_HEAT_SEED=4,
       TD3_HEAT_SAMPLE=8, TD3_HEAT_WINDOW=16, TD3_HEAT_ACCOUNTING=32,
       TD3_HEAT_SAMPLE_FRESH=64, TD3_HEAT_WINDOW_FRESH=128,
       TD3_HEAT_LOCKED=256 };
/* Diagnostic extension only; never training telemetry or start permission.
 * Safety-task owner captures once BEFORE fragmenting. No mutation/check/clear.
 * Unknown numbers are NaN / UINT64_MAX and explicitly invalidated by flags.
 * LE IEEE-754 binary32/binary64, CRC32, canonical 144 bytes; not struct memcpy.
 * Bind to the zero-capability thermal firmware's HELLO nonce and boot token.
 * Use the existing sole CAN sender/Tx event deadline, never a second writer. */
int motor_td3_thermal_can_packet(uint8_t out[TD3_THERMAL_CAN_BYTES],
    const motor_td3_thermal_feed *,uint64_t nonce,uint64_t boot,
    uint32_t snapshot_seq,uint64_t now_us);
#endif
