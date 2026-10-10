#include "motor_td3_can_control.h"
#include <math.h>
#include <string.h>
static void trip(motor_td3_can_control *c,int fault) {
    if(fault==TD3_CAN_PROTOCOL_FAULT) c->protocol_fault=1;
    motor_td3_stop(&c->guard); if(!c->guard.fault) c->guard.fault=fault;
    c->hooks.disable(c->hooks.user);
}
int motor_td3_can_control_init_locked(motor_td3_can_control *c,const motor_td3_can_hooks *h,
    uint64_t boot,const char *fw,const char *profile) {
    uint8_t check[TD3_CAN_MAX_PACKET];
    if(!c||!h||!h->disable||!h->begin||!h->apply||!h->snapshot) return 0;
    memset(c,0,sizeof(*c)); c->hooks=*h; h->disable(h->user);
    if(!boot||!motor_td3_can_hello(check,1,boot,0,fw,profile)) return 0;
    c->boot=boot; c->guard.fault=TD3_CAN_NOT_READY;
    strcpy(c->firmware,fw); strcpy(c->profile,profile); return 1;
}
int motor_td3_can_control_init(motor_td3_can_control *c,const motor_td3_limits *limits,
    const motor_td3_can_hooks *hooks,uint64_t boot,const char *fw,const char *profile,
    const float *refs,unsigned count,uint32_t age,uint16_t caps) {
    uint8_t check[TD3_CAN_MAX_PACKET]; unsigned i;
    if(!c||!hooks||!hooks->disable||!hooks->begin||!hooks->apply||!hooks->snapshot||!limits) return 0;
    memset(c,0,sizeof(*c)); c->hooks=*hooks; c->hooks.disable(c->hooks.user);
    if(!boot||!age||!refs||!count||count>64||!motor_td3_can_hello(check,1,boot,caps,fw,profile)) return 0;
    for(i=0;i<count;i++) if(!isfinite(refs[i])||fabsf(refs[i])>=limits->speed_limit) return 0;
    if(!motor_td3_init(&c->guard,limits)) return 0;
    c->boot=boot; c->max_age_us=age; c->capabilities=caps; c->references=refs; c->reference_count=count;
    strcpy(c->firmware,fw); strcpy(c->profile,profile); return 1;
}
int motor_td3_can_receive(motor_td3_can_control *c,uint16_t id,int standard,const uint8_t f[8],size_t dlc,uint64_t now) {
    int result;
    if(!c) return -1;
    if(id!=TD3_CAN_REQUEST_ID) return 0;
    if(!standard) { c->rx_fault=1; return -1; }
    result=motor_td3_can_feed(&c->rx,f,dlc,now);
    if(result<0) c->rx_fault=1;
    if(result==1) {
        if(c->queued||!motor_td3_can_decode(c->rx.bytes,c->rx.length,&c->pending)) { c->rx_fault=1; return -1; }
        c->queued=1;
    }
    return result;
}
static int snapshot(motor_td3_can_control *c,motor_td3_telemetry *t) {
    memset(t,0,sizeof(*t)); return c->hooks.snapshot(c->hooks.user,t);
}
static int actual(motor_td3_can_control *c,const motor_td3_guard *g) {
    motor_td3_telemetry t;
    return snapshot(c,&t)&&t.enabled==g->enabled&&(!g->enabled||(t.kp==g->kp&&t.ki==g->ki));
}
void motor_td3_can_control_tick_ready(motor_td3_can_control *c,uint64_t now,int estop,int gain_ready) {
    motor_td3_telemetry t; motor_td3_can_command cmd; motor_td3_guard next; unsigned i; int ok=0;
    if(!c) return;
    if(c->rx.active&&(now<c->rx.last_us||now-c->rx.started_us>=TD3_CAN_FRAGMENT_TIMEOUT_US)) c->rx_fault=1;
    if(c->rx_fault) trip(c,TD3_CAN_PROTOCOL_FAULT);
    if(!snapshot(c,&t)) { trip(c,TD3_CAN_BOARD_FAULT); return; }
    motor_td3_tick(&c->guard,now,t.current,t.speed,t.vbus,t.temperature_c,estop);
    if(c->guard.fault) c->hooks.disable(c->hooks.user);
    if(c->queued && (gain_ready || c->pending.command.type==TD3_HELLO ||
                    c->pending.command.type==TD3_STOP || now>=c->pending.expires_us || c->guard.fault)) {
        cmd=c->pending; c->queued=0;
        if(cmd.command.type==TD3_HELLO) {
            if(c->owner||c->guard.enabled||strcmp(cmd.command.profile_id,c->profile)) trip(c,TD3_CAN_PROTOCOL_FAULT);
            else { c->owner=1; c->nonce=cmd.nonce; c->hello_pending=1; }
        } else if(!c->owner||cmd.nonce!=c->nonce||cmd.boot!=c->boot||c->wire_seq==UINT32_MAX||cmd.wire_seq!=c->wire_seq+1U) {
            trip(c,TD3_CAN_PROTOCOL_FAULT);
        } else if(cmd.command.type==TD3_STOP) {
            motor_td3_stop(&c->guard); c->hooks.disable(c->hooks.user); c->wire_seq=cmd.wire_seq;
        } else if(now>=cmd.expires_us||cmd.expires_us-now>c->max_age_us||c->capabilities!=TD3_CAN_CAPABILITIES_ALL) {
            trip(c,TD3_CAN_PROTOCOL_FAULT);
        } else if(!c->guard.fault) {
            next=c->guard;
            if(cmd.command.type==TD3_BEGIN) {
                for(i=0;i<c->reference_count;i++) if(cmd.command.speed_ref==c->references[i]) ok=1;
                if(ok) ok=motor_td3_begin(&next,now,cmd.command.lease_ms*1000U);
                if(ok) {
                    motor_td3_tick(&next,now,t.current,t.speed,t.vbus,t.temperature_c,estop);
                    ok=next.enabled&&!next.fault;
                }
                if(ok) {
                    ok=c->hooks.begin(c->hooks.user,cmd.command.speed_ref,next.kp,next.ki);
                    if(ok) next.t_apply_us=now;
                }
            } else {
                ok=motor_td3_apply(&next,now,cmd.command.command_seq,cmd.command.kp,cmd.command.ki,cmd.command.lease_ms*1000U);
                if(ok) ok=c->hooks.apply(c->hooks.user,next.kp,next.ki);
            }
            if(ok&&actual(c,&next)) { c->guard=next; c->wire_seq=cmd.wire_seq; }
            else trip(c,next.fault?next.fault:TD3_CAN_BOARD_FAULT);
        }
    }
    if(!actual(c,&c->guard)) trip(c,TD3_CAN_BOARD_FAULT);
}
void motor_td3_can_control_tick(motor_td3_can_control *c,uint64_t now,int estop) {
    motor_td3_can_control_tick_ready(c,now,estop,1);
}
int motor_td3_can_make_hello(motor_td3_can_control *c,uint8_t out[TD3_CAN_MAX_PACKET]) {
    int n;
    if(!c||!c->hello_pending) return 0;
    n=motor_td3_can_hello(out,c->nonce,c->boot,c->capabilities,c->firmware,c->profile);
    if(n) c->hello_pending=0;
    return n;
}
int motor_td3_can_make_telemetry(motor_td3_can_control *c,uint8_t out[TD3_CAN_MAX_PACKET]) {
    motor_td3_telemetry t;
    if(!c||!c->owner||c->telemetry_seq==UINT32_MAX||!actual(c,&c->guard)||!snapshot(c,&t)) return 0;
    t.seq=++c->telemetry_seq; t.t_us=c->guard.last_tick_us; t.t_apply_us=c->guard.t_apply_us;
    t.applied_seq=c->guard.applied_seq; t.fault=(uint32_t)c->guard.fault;
    /* Physical enable/gains from board snapshot; not copied from received command. */
    return motor_td3_can_telemetry(out,c->nonce,c->boot,&t);
}
