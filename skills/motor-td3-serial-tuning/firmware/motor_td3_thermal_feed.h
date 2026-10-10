#ifndef MOTOR_TD3_THERMAL_FEED_H
#define MOTOR_TD3_THERMAL_FEED_H
#include "motor_td3_thermal.h"

/* Zero-initialize storage; init ONCE per boot. Serialize all calls in the safety
 * owner. A driver must provide actual trigger timestamps, complete three-phase
 * conversions, valid PWM sampling windows, and overrun/error status. Do not
 * generate timestamps from a requested schedule to hide missing samples.
 * No PWM-enable, calibration-writing, cooling, reset or rearm API exists.
 */
enum { TD3_FEED_INIT=1, TD3_FEED_CALIBRATION=2, TD3_FEED_THERMAL=3,
       TD3_FEED_ADC=4, TD3_FEED_SEQUENCE=5, TD3_FEED_TIME=6,
       TD3_FEED_STALE=7, TD3_FEED_PEAK=8 };
typedef struct {
    float zero_adc[3], gain_a_per_count[3];
    uint16_t verified_low_adc[3], verified_high_adc[3];
    unsigned calibrated; /* trusted, read-only engineering record, never TD3 */
} motor_td3_current_calibration;
typedef struct {
    uint64_t sequence, capture_us;
    uint16_t raw_adc[3]; /* A=ADC1 JDR1, B=ADC2 JDR1, C=ADC1 JDR2 */
    float speed_rpm;
    unsigned valid, output_active; /* any bridge activity since prior sample */
} motor_td3_thermal_sample;
typedef struct {
    motor_td3_thermal guard;
    motor_td3_current_calibration calibration;
    motor_td3_thermal_window window;
    uint64_t sample_sequence, last_capture_us, last_now_us;
    uint32_t period_us;
    float min_abs_speed_rpm;
    unsigned initialized, fault, window_active;
    void (*disable)(void *);
    void *user;
} motor_td3_thermal_feed;
int motor_td3_thermal_feed_init(motor_td3_thermal_feed *,
    const motor_td3_current_calibration *, const motor_td3_thermal_limits *,
    const motor_td3_thermal_seed *, uint64_t, void (*disable)(void *), void *);
int motor_td3_thermal_feed_sample(motor_td3_thermal_feed *, const motor_td3_thermal_sample *, uint64_t now_us);
/* Call independently of ADC/CAN activity. Hardware watchdog must supervise this owner. */
int motor_td3_thermal_feed_check(motor_td3_thermal_feed *, uint64_t now_us);
int motor_td3_thermal_feed_may_start(motor_td3_thermal_feed *, uint64_t now_us);
#endif
