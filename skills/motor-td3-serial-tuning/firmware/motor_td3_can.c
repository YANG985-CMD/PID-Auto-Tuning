#include "motor_td3_can.h"
#include <math.h>
#include <string.h>
static uint32_t crc(const uint8_t *p,size_t n) {
    uint32_t c=0xffffffffU; size_t i; unsigned k;
    for(i=0;i<n;i++) { c^=p[i]; for(k=0;k<8;k++) c=(c>>1)^((c&1)?0xedb88320U:0U); }
    return c^0xffffffffU;
}
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint64_t u64(const uint8_t *p) { return u32(p)|((uint64_t)u32(p+4)<<32); }
static void put32(uint8_t *p,uint32_t v) { unsigned i; for(i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i)); }
static void put64(uint8_t *p,uint64_t v) { put32(p,(uint32_t)v); put32(p+4,(uint32_t)(v>>32)); }
static float real32(const uint8_t *p) { uint32_t u=u32(p); float f; memcpy(&f,&u,4); return f; }
static void putreal(uint8_t *p,float f) { uint32_t u; memcpy(&u,&f,4); put32(p,u); }
static int idlen(const char *s) {
    int n=0; if(!s) return 0;
    for(;*s;s++,n++) if(n>=64||!((*s>='a'&&*s<='z')||(*s>='A'&&*s<='Z')||
            (*s>='0'&&*s<='9')||*s=='-'||*s=='_'||*s=='.')) return 0;
    return n;
}
int motor_td3_can_feed(motor_td3_can_rx *r,const uint8_t f[8],size_t dlc,uint64_t now) {
    unsigned n,i;
    if(!r||!f) return -1;
    if(now<r->last_us||(r->active&&now-r->started_us>=TD3_CAN_FRAGMENT_TIMEOUT_US)) goto bad;
    r->last_us=now;
    if(dlc!=8||f[0]!=0xD1||f[3]<36||f[3]>TD3_CAN_MAX_PACKET) goto bad;
    if(!r->active) {
        if(f[2]) goto bad;
        r->active=1; r->started_us=now; r->transfer=f[1]; r->index=0; r->length=f[3]; r->used=0;
    }
    if(f[1]!=r->transfer||f[2]!=r->index||f[3]!=r->length) goto bad;
    n=r->length-r->used; if(n>4) n=4;
    for(i=n;i<4;i++) if(f[4+i]) goto bad;
    memcpy(r->bytes+r->used,f+4,n); r->used=(uint16_t)(r->used+n); r->index++;
    if(r->used==r->length) {
        r->active=0;
        if(crc(r->bytes,r->length-4)!=u32(r->bytes+r->length-4)) goto bad;
        return 1;
    }
    return 0;
bad: r->active=0; return -1;
}
int motor_td3_can_fragment(const uint8_t *p,size_t len,uint8_t transfer,unsigned index,uint8_t out[8]) {
    size_t offset=(size_t)index*4,n;
    if(!p||!out||len<36||len>TD3_CAN_MAX_PACKET||offset>=len) return 0;
    out[0]=0xD1; out[1]=transfer; out[2]=(uint8_t)index; out[3]=(uint8_t)len;
    n=len-offset; if(n>4) n=4; memset(out+4,0,4); memcpy(out+4,p+offset,n); return 1;
}
int motor_td3_can_decode(const uint8_t *p,size_t len,motor_td3_can_command *out) {
    motor_td3_can_command x; unsigned type,n; const uint8_t *b;
    if(!p||!out||len<36||len>TD3_CAN_MAX_PACKET||p[0]!=1||p[2]||p[3]||
            crc(p,len-4)!=u32(p+len-4)) return 0;
    memset(&x,0,sizeof(x)); type=p[1]; b=p+32;
    x.nonce=u64(p+4); x.boot=u64(p+12); x.wire_seq=u32(p+20); x.expires_us=u64(p+24);
    if(!x.nonce||type<1||type>4) return 0;
    x.command.type=(int)type;
    if(type==TD3_HELLO) {
        n=b[0]; if(!n||n>64||len!=37U+n||x.boot||x.wire_seq||x.expires_us) return 0;
        memcpy(x.command.profile_id,b+1,n);
        if(idlen(x.command.profile_id)!=(int)n) return 0;
    } else {
        if(!x.boot||!x.wire_seq||(type!=TD3_STOP&&!x.expires_us)) return 0;
        if(type==TD3_BEGIN) {
            if(len!=44) return 0;
            x.command.speed_ref=real32(b); x.command.lease_ms=u32(b+4);
        } else if(type==TD3_GAINS) {
            if(len!=52) return 0;
            x.command.command_seq=u32(b); x.command.kp=real32(b+4); x.command.ki=real32(b+8); x.command.lease_ms=u32(b+12);
            if(!x.command.command_seq) return 0;
        } else if(len!=36) return 0;
        if(type!=TD3_STOP&&(!x.command.lease_ms||x.command.lease_ms>4294967U)) return 0;
    }
    if(!isfinite(x.command.speed_ref)||!isfinite(x.command.kp)||!isfinite(x.command.ki)) return 0;
    *out=x; return 1;
}
static void header(uint8_t *p,unsigned type,uint64_t nonce,uint64_t boot,uint32_t seq) {
    memset(p,0,32); p[0]=1; p[1]=(uint8_t)type; put64(p+4,nonce); put64(p+12,boot); put32(p+20,seq);
}
int motor_td3_can_hello(uint8_t out[TD3_CAN_MAX_PACKET],uint64_t nonce,uint64_t boot,uint16_t caps,const char *fw,const char *profile) {
    int nf=idlen(fw),np=idlen(profile),n;
    if(!out||!nonce||!boot||!nf||!np||(caps&~63U)) return 0;
    header(out,0x81,nonce,boot,0); out[32]=(uint8_t)caps; out[33]=(uint8_t)(caps>>8);
    out[34]=(uint8_t)nf; memcpy(out+35,fw,(size_t)nf); out[35+nf]=(uint8_t)np; memcpy(out+36+nf,profile,(size_t)np);
    n=36+nf+np; put32(out+n,crc(out,(size_t)n)); return n+4;
}
int motor_td3_can_telemetry(uint8_t out[TD3_CAN_MAX_PACKET],uint64_t nonce,uint64_t boot,const motor_td3_telemetry *t) {
    float values[10]; unsigned i;
    if(!out||!t||!nonce||!boot||(t->enabled!=0&&t->enabled!=1)||t->t_apply_us>t->t_us) return 0;
    values[0]=t->speed_ref; values[1]=t->speed; values[2]=t->error_history; values[3]=t->integral_output;
    values[4]=t->current; values[5]=t->vbus; values[6]=t->temperature_c; values[7]=t->kp; values[8]=t->ki; values[9]=t->elapsed_ms;
    for(i=0;i<10;i++) if(!isfinite(values[i])) return 0;
    header(out,0x82,nonce,boot,t->seq);
    put64(out+32,t->t_us); put64(out+40,t->t_apply_us); put32(out+48,t->applied_seq); put32(out+52,t->fault);
    out[56]=(uint8_t)t->enabled; memset(out+57,0,3);
    for(i=0;i<10;i++) putreal(out+60+4*i,values[i]);
    put32(out+100,crc(out,100)); return 104;
}
