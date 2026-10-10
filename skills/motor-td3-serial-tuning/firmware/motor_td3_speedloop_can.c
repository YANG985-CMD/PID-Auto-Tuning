#include "motor_td3_speedloop_can.h"
#include "motor_td3_speedloop_pi_bind.h"
#include "FOC_Model.h"
#include <math.h>
#include <string.h>

static void disable(void *user) {
    motor_td3_speedloop_can *s=user;s->board.disable(s->board.user);
}
static int snapshot(void *user,motor_td3_telemetry *t) {
    motor_td3_speedloop_can *s=user;
    return s->board.snapshot(s->board.user,t);
}
static int apply(void *user,float kp,float ki) {
    motor_td3_speedloop_can *s=user;const motor_td3_can_command *cmd=&s->endpoint->pending;
    uint64_t lease=(uint64_t)cmd->command.lease_ms*1000U;
    if(!s->in_boundary||s->reset||s->applied||UINT64_MAX-s->now_us<lease) return 0;
    /* Wire sequence is monotonic across BEGIN and GAINS. Protocol applied_seq
     * remains the action's command_seq; its guard commits after actual(). */
    if(!motor_td3_speedloop_pi_queue(TD3_SPEEDLOOP_EXTERNAL,cmd->wire_seq,kp,ki,s->now_us+lease)) return 0;
    if(!motor_td3_speedloop_pi_boundary(&motor_td3_speedloop_pi_state,s->now_us,s->error,0,
                                      s->integral,&spd_kpki.spd_kp,&spd_kpki.spd_ki)) return 0;
    s->applied=1;return 1;
}
static int begin(void *user,float ref,float kp,float ki) {
    motor_td3_speedloop_can *s=user;
    return apply(user,kp,ki)&&s->board.begin(s->board.user,ref,kp,ki);
}
static int boundary(void *user,uint64_t now,float error,int reset,float *integral) {
    motor_td3_speedloop_can *s=user;int ok;
    s->now_us=now;s->error=error;s->integral=integral;s->reset=reset;s->applied=0;s->in_boundary=1;
    motor_td3_can_control_tick_ready(s->endpoint,now,s->estop,!reset);
    ok=s->applied||motor_td3_speedloop_pi_boundary(&motor_td3_speedloop_pi_state,now,error,reset,
                                                integral,&spd_kpki.spd_kp,&spd_kpki.spd_ki);
    s->in_boundary=0;s->integral=0;s->previous_error=error;
    if(!ok||motor_td3_speedloop_pi_state.fault||
       (s->endpoint->capabilities&&s->endpoint->guard.fault)) { disable(s);return 0; }
    return 1;
}
int motor_td3_speedloop_can_attach(motor_td3_speedloop_can *s,motor_td3_can_control *endpoint,
                                  const motor_td3_can_hooks *board,motor_td3_can_hooks *out) {
    if(!s||!endpoint||!board||!out||!board->disable||!board->begin||!board->snapshot) return 0;
    memset(s,0,sizeof(*s));s->endpoint=endpoint;s->board=*board;s->previous_error=NAN;
    if(!motor_td3_speedloop_pi_set_service(boundary,s)) return 0;
    out->user=s;out->disable=disable;out->begin=begin;out->apply=apply;out->snapshot=snapshot;
    return 1;
}
