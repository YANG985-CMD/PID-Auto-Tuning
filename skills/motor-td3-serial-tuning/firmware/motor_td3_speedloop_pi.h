#ifndef MOTOR_TD3_SPEEDLOOP_PI_H
#define MOTOR_TD3_SPEEDLOOP_PI_H
#include <stdint.h>

enum { TD3_SPEEDLOOP_FUZZY=0, TD3_SPEEDLOOP_FIXED=1, TD3_SPEEDLOOP_EXTERNAL=2 };
enum { TD3_PI_OK=0,TD3_PI_ARGUMENT=1,TD3_PI_RANGE=2,TD3_PI_SEQUENCE=3,
       TD3_PI_BUSY=4,TD3_PI_EXPIRED=5,TD3_PI_NUMERIC=6,TD3_PI_CLOCK=7,TD3_PI_OWNER=8 };
/* These are the 17.SpeedLoop source defaults, not calibrated safety limits. */
#define TD3_SPEEDLOOP_KP 0.003389f
#define TD3_SPEEDLOOP_KI 0.00144f

typedef struct {
    float kp_min,kp_max,ki_min,ki_max;
} motor_td3_speedloop_pi_domain;
typedef struct {
    motor_td3_speedloop_pi_domain domain;
    float pending_kp,pending_ki,actual_kp,actual_ki,integral_output;
    float sum_before,sum_after;
    uint64_t control_us,applied_us,deadline_us,pending_deadline_us;
    uint32_t last_queued_seq,applied_seq;
    unsigned mode,pending_mode,pending,fault,initialized;
} motor_td3_speedloop_pi;

/* Single owner in the ADC/control task. Stage must be serialized with boundary;
 * this module neither enables PWM nor provides a motor safety authorization. */
int motor_td3_speedloop_pi_init(motor_td3_speedloop_pi *,const motor_td3_speedloop_pi_domain *);
int motor_td3_speedloop_pi_stage(motor_td3_speedloop_pi *,unsigned mode,uint32_t sequence,
                               float kp,float ki,uint64_t deadline_us);
/* Called inside the actual 1ms PI task AFTER its previous-input integration,
 * BEFORE Kp*error+integral and Ki*error. Reset has priority over an update.
 * A false return requires the board caller to disable physical outputs. */
int motor_td3_speedloop_pi_boundary(motor_td3_speedloop_pi *,uint64_t now_us,float error,
                                  int model_reset,float *integral,float *kp,float *ki);
#endif
