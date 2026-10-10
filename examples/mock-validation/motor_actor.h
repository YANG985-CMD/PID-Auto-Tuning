#ifndef MOTOR_ACTOR_H
#define MOTOR_ACTOR_H
/* raw: rpm,rpm,rpm,rpm,A,A,V,Kp,Ki,ms. No allocation, no training on MCU.
 * Return 0 on invalid input; caller must invoke its validated safe-stop path.
 * Inference must not bypass the independent firmware guard. */
int motor_actor_predict(const float raw[10], float action[2], float gains[2]);
#endif
