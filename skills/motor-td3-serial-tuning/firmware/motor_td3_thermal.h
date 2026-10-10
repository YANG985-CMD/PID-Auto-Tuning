#ifndef MOTOR_TD3_THERMAL_H
#define MOTOR_TD3_THERMAL_H
#include <stdint.h>

/* Sensorless winding OVERLOAD budget, not temperature in degrees C.
 * Configuration and seed must come from a validated board procedure, never
 * from TD3, CAN commands or a default cold-start assumption. Initialize once
 * per boot; retain state across STOP/BEGIN. No automatic cooling or rearm.
 * This module does not replace hardware overcurrent or power-stage protection.
 * Serialize all calls in the safety task. Independently call check() even when
 * ADC observations stop. The disable hook must turn the actual phase bridge off.
 */
enum { TD3_THERMAL_CONFIG=1, TD3_THERMAL_BOOT_UNKNOWN=2,
       TD3_THERMAL_SENSOR=3, TD3_THERMAL_SEQUENCE=4, TD3_THERMAL_TIME=5,
       TD3_THERMAL_STALE=6, TD3_THERMAL_CURRENT=7, TD3_THERMAL_BUDGET=8,
       TD3_THERMAL_STALL=9, TD3_THERMAL_DURATION=10 };
typedef struct {
    float continuous_rms_a[3], instantaneous_trip_a[3], budget_a2s[3];
    float stall_speed_rpm, stall_rms_a;
    uint32_t window_us, window_samples, max_age_us;
    uint64_t max_energized_us, max_stalled_us;
    unsigned validated; /* engineering evidence; production read-only constant */
} motor_td3_thermal_limits;
typedef struct {
    double used_a2s[3];
    uint64_t energized_us, stalled_us;
    unsigned known; /* authenticated retained state or verified cold procedure */
} motor_td3_thermal_seed;
typedef struct {
    uint64_t seq, end_us;
    uint32_t samples;
    float mean_square_a2[3], peak_abs_a[3], min_abs_speed_rpm;
    unsigned valid, output_active; /* any bridge activity during this window */
} motor_td3_thermal_observation;
typedef struct {
    motor_td3_thermal_limits limits;
    double used_a2s[3];
    uint64_t last_end_us, last_now_us, sequence, energized_us, stalled_us;
    unsigned fault, has_window, configured, seed_known;
    void (*disable)(void *);
    void *user;
} motor_td3_thermal;
/* Small current-square collector: add each COMPLETE calibrated simultaneous
 * phase sample, including negative currents. Finish at the configured count.
 * Time, contiguous sequence and ADC coverage are checked by the guard/caller.
 */
typedef struct {
    float sum_a2[3], peak_abs_a[3];
    uint32_t samples;
    unsigned invalid;
} motor_td3_thermal_window;
void motor_td3_thermal_window_init(motor_td3_thermal_window *);
int motor_td3_thermal_window_add(motor_td3_thermal_window *, const float phase_a[3], unsigned valid);
int motor_td3_thermal_window_finish(const motor_td3_thermal_window *, motor_td3_thermal_observation *);
int motor_td3_thermal_init(motor_td3_thermal *, const motor_td3_thermal_limits *,
    const motor_td3_thermal_seed *, uint64_t now_us, void (*disable)(void *), void *user);
int motor_td3_thermal_observe(motor_td3_thermal *, const motor_td3_thermal_observation *, uint64_t now_us);
int motor_td3_thermal_check(motor_td3_thermal *, uint64_t now_us);
/* Permission only; never enables PWM. Requires a fresh completed window. */
int motor_td3_thermal_may_start(motor_td3_thermal *, uint64_t now_us);
float motor_td3_thermal_load(const motor_td3_thermal *); /* max phase H/H_limit */
#endif
