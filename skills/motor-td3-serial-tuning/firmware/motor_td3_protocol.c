#include "motor_td3_protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#include <ctype.h>

static uint32_t crc32(const char *p,size_t n) {
    uint32_t c=0xffffffffu; size_t i; int k;
    for(i=0;i<n;i++) { c^=(unsigned char)p[i]; for(k=0;k<8;k++) c=(c>>1)^((c&1)?0xedb88320u:0u); }
    return c^0xffffffffu;
}
static int ident(const char *s) {
    size_t n=0; if(!s||!*s) return 0;
    for(;*s;s++,n++) if(n>=95||!(isalnum((unsigned char)*s)||*s=='-'||*s=='_'||*s=='.')) return 0;
    return 1;
}
static void space(const char **p) { while(**p==' '||**p=='\t'||**p=='\r') (*p)++; }
static int string_value(const char **p,char *out,size_t cap) {
    size_t n=0; space(p); if(*(*p)++!='"') return 0;
    while(**p&&**p!='"') { unsigned char c=(unsigned char)*(*p)++;
        if(n+1>=cap||c<32||c>126||c=='\\') return 0;
        out[n++]=(char)c;
    }
    if(*(*p)++!='"') return 0;
    out[n]=0; return 1;
}
static int numeric(const char **p,double *value) {
    const char *start,*q; char token[64],*end; size_t n;
    space(p); start=q=*p;
    if(*q=='-') q++;
    if(*q=='0') q++; else { if(*q<'1'||*q>'9') return 0; while(isdigit((unsigned char)*q)) q++; }
    if(*q=='.') { q++; if(!isdigit((unsigned char)*q)) return 0; while(isdigit((unsigned char)*q)) q++; }
    if(*q=='e'||*q=='E') { q++; if(*q=='+'||*q=='-') q++; if(!isdigit((unsigned char)*q)) return 0; while(isdigit((unsigned char)*q)) q++; }
    n=(size_t)(q-start); if(n==0||n>=sizeof(token)) return 0;
    memcpy(token,start,n); token[n]=0; errno=0; *value=strtod(token,&end);
    if(errno||*end||!isfinite(*value)) return 0;
    *p=q; return 1;
}
int motor_td3_decode(const char *frame,size_t length,motor_td3_command *command) {
    char json[1024],key[40],type[24]; const char *p; uint32_t supplied=0,seen=0; size_t n,i; double value;
    if(!frame||!command||length<12||length>sizeof(json)||frame[length-1]!='\n') return 0;
    n=length-10; if(frame[n]!='*') return 0;
    for(i=n+1;i<n+9;i++) { char c=frame[i]; uint32_t digit;
        if(c>='0'&&c<='9') digit=(uint32_t)(c-'0');
        else if(c>='a'&&c<='f') digit=(uint32_t)(c-'a'+10);
        else if(c>='A'&&c<='F') digit=(uint32_t)(c-'A'+10); else return 0;
        supplied=(supplied<<4)|digit;
    }
    if(supplied!=crc32(frame,n)) return 0;
    memcpy(json,frame,n); json[n]=0; p=json; memset(command,0,sizeof(*command));
    space(&p); if(*p++!='{') return 0;
    while(1) { uint32_t bit=0;
        if(!string_value(&p,key,sizeof(key))) return 0;
        space(&p); if(*p++!=':') return 0;
        if(!strcmp(key,"type")) {
            bit=1; if(!string_value(&p,type,sizeof(type))) return 0;
            if(!strcmp(type,"hello")) command->type=TD3_HELLO;
            else if(!strcmp(type,"begin")) command->type=TD3_BEGIN;
            else if(!strcmp(type,"gains")) command->type=TD3_GAINS;
            else if(!strcmp(type,"stop")) command->type=TD3_STOP; else return 0;
        } else if(!strcmp(key,"profile_id")) {
            bit=2; if(!string_value(&p,command->profile_id,sizeof(command->profile_id))||!ident(command->profile_id)) return 0;
        } else {
            if(!numeric(&p,&value)) return 0;
            if(!strcmp(key,"command_seq")) { bit=4; if(value<1||value>4294967295.0||floor(value)!=value) return 0; command->command_seq=(uint32_t)value; }
            else if(!strcmp(key,"lease_ms")) { bit=8; if(value<1||value>4294967.0||floor(value)!=value) return 0; command->lease_ms=(uint32_t)value; }
            else if(!strcmp(key,"kp")) { bit=16; command->kp=(float)value; }
            else if(!strcmp(key,"ki")) { bit=32; command->ki=(float)value; }
            else if(!strcmp(key,"speed_ref")) { bit=64; command->speed_ref=(float)value; }
            else return 0;
            if(!isfinite(command->kp)||!isfinite(command->ki)||!isfinite(command->speed_ref)) return 0;
        }
        if(seen&bit) return 0;
        seen|=bit; space(&p);
        if(*p=='}') { p++; break; }
        if(*p++!=',') return 0;
    }
    space(&p); if(*p) return 0;
    return (command->type==TD3_HELLO&&seen==3)||(command->type==TD3_BEGIN&&seen==75)||
           (command->type==TD3_GAINS&&seen==61)||(command->type==TD3_STOP&&seen==1);
}
static int finish(char *out,size_t cap,int n) {
    int tail; if(n<0||(size_t)n+10>=cap) return 0;
    tail=snprintf(out+n,cap-(size_t)n,"*%08lx\n",(unsigned long)crc32(out,(size_t)n));
    return tail==10 ? n+tail : 0;
}
int motor_td3_encode_hello(char *out,size_t cap,const char *fw,const char *profile,const char *boot) {
    int n; if(!out||!ident(fw)||!ident(profile)||!ident(boot)) return 0;
    n=snprintf(out,cap,"{\"type\":\"hello\",\"protocol_id\":\"motor-td3-json-crc-v1\",\"firmware_id\":\"%s\",\"profile_id\":\"%s\",\"boot_id\":\"%s\",\"capabilities\":[\"atomic_gains\",\"applied_feedback\",\"lease\",\"link_watchdog\",\"fault_latch\",\"single_owner\"]}",fw,profile,boot);
    return finish(out,cap,n);
}
int motor_td3_encode_telemetry(char *out,size_t cap,const char *boot,const motor_td3_telemetry *t) {
    int n; if(!out||!t||!ident(boot)) return 0;
    if(!isfinite(t->speed_ref)||!isfinite(t->speed)||!isfinite(t->error_history)||!isfinite(t->integral_output)||
       !isfinite(t->current)||!isfinite(t->vbus)||!isfinite(t->temperature_c)||!isfinite(t->kp)||!isfinite(t->ki)||!isfinite(t->elapsed_ms)) return 0;
    n=snprintf(out,cap,"{\"type\":\"telemetry\",\"boot_id\":\"%s\",\"seq\":%lu,\"t_us\":%llu,\"t_apply_us\":%llu,\"applied_seq\":%lu,\"fault\":%lu,\"enabled\":%s,\"speed_ref\":%.9g,\"speed\":%.9g,\"error_history\":%.9g,\"integral_output\":%.9g,\"current\":%.9g,\"vbus\":%.9g,\"temperature_c\":%.9g,\"kp\":%.9g,\"ki\":%.9g,\"elapsed_ms\":%.9g}",
       boot,(unsigned long)t->seq,(unsigned long long)t->t_us,(unsigned long long)t->t_apply_us,
       (unsigned long)t->applied_seq,(unsigned long)t->fault,t->enabled?"true":"false",
       (double)t->speed_ref,(double)t->speed,(double)t->error_history,(double)t->integral_output,
       (double)t->current,(double)t->vbus,(double)t->temperature_c,(double)t->kp,(double)t->ki,(double)t->elapsed_ms);
    return finish(out,cap,n);
}
