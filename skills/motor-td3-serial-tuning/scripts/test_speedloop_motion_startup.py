"""Exercise the actual private motion adapter/model using host HAL substitutes.

No probe, power, motor, serial or CAN hardware access. Outputs are temporary.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import zlib

import can_transport as wire
from test_g431_integration import STUB

SKILL = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "fuzzy_pid.h"
FuzzyPID_t fuzzy_speed_pid;
static uint64_t host_us;
uint32_t test_primask;
static unsigned preempt_armed,preempt_suppressed;
static void inject_adc_boundary(void);
uint64_t motor_td3_speedloop_pi_host_time_us(void) {
    uint64_t captured=host_us;
    if(preempt_armed) {
        preempt_armed=0;
        if(test_primask) ++preempt_suppressed;
        else {host_us+=100;inject_adc_boundary();}
    }
    return captured;
}
#include "adapter_host.c"
#include <assert.h>
#include <stdio.h>
static void inject_adc_boundary(void) {
    float integral=0;
    assert(motor_td3_speedloop_pi_model_boundary(1000,0,&integral));
}
HAL_StatusTypeDef HAL_FDCAN_GetTxEvent(FDCAN_HandleTypeDef *h,FDCAN_TxEventFifoTypeDef *e) {
    (void)h;memset(e,0,sizeof(*e));return HAL_OK;
}
static void fresh(uint64_t boot) {
    test_primask=preempt_armed=preempt_suppressed=0;
    memset(&test_tim,0,sizeof(test_tim));memset(&test_rcc,0,sizeof(test_rcc));
    memset(&test_gpio,0,sizeof(test_gpio));memset(&test_gpioa,0,sizeof(test_gpioa));
    memset(&endpoint,0,sizeof(endpoint));
    ring_write=ring_read=irq_fault=initialized=adc_samples=hall_bad=0;
    now_us=main_seen_us=adc_seen_us=bus_seen_us=tx_started_us=diag_due_us=0;
    tx_length=tx_index=diag_index=tx_transfer=endpoint_ready=motion_enabled=0;
    tx_inflight=tx_frame_id=tx_marker=0;tx_queued_us=0;
    Motor_state=ADC_offset=0;Ia=Ib=Ic=Vbus=HallSpeed=HallThetaAdd=0;
    host_us=1000;FOC_Model_initialize();
    FuzzyPID_Init(&fuzzy_speed_pid,.003389f,.00144f,0,500,100);
    motor_td3_speedloop_pi_bind_init();
    test_rcc.APB2ENR=RCC_APB2ENR_TIM1EN;
    test_gpio.IDR=1U<<8;freelevel=3;available=send_error=unlock_tick_countdown=0;
    motor_td3_g431_debugger_boot_token=boot;
    motor_td3_g431_init();
}
int main(void) {
    fresh(0);assert(!endpoint_ready&&irq_fault&&test_off());
    assert(!motor_td3_g431_sampling_ready());
    fresh(0x1234567812345678ULL);
    assert(endpoint_ready&&!irq_fault&&!endpoint.guard.fault);
    assert(endpoint.reference_count==1&&endpoint.references[0]==1000);
    assert(endpoint.boot==0x1234567812345678ULL&&!motor_td3_g431_debugger_boot_token);
    test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    assert(motor_td3_g431_sampling_ready()&&test_ch4());
    assert((test_tim.BDTR&TIM_BDTR_MOE)&&!(test_tim.CCER&TD3_G431_PHASE_MASK));
    assert((test_gpioa.MODER&0x3f0000U)==0x150000U);
    assert((test_gpio.MODER&0xfc000000U)==0x54000000U);
    /* Startup calibration may be pending: idle tick must preserve CH4. */
    motor_td3_g431_poll();motor_td3_g431_tick_1ms();
    assert(!endpoint.guard.fault&&!irq_fault&&(test_tim.BDTR&TIM_BDTR_MOE));
    assert(!motion_begin(0,1000,.003389f,.00144f)&&test_off());
    fresh(10);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    preempt_armed=1;motor_td3_g431_tick_1ms();
    assert(preempt_suppressed==1&&!endpoint.guard.fault);
    fresh(11);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    host_us+=5000;motor_td3_g431_tick_1ms();assert(irq_fault&&test_off());
    fresh(8);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    assert(motor_td3_g431_sampling_ready());
    ADC_offset=1;Vbus=24;
    for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
    motor_td3_g431_bus_sample();
    assert(motion_begin(0,1000,.003389f,.00144f));
    assert((test_tim.CCER&TD3_G431_PHASE_MASK)==TD3_G431_PHASE_MASK);
    assert(Motor_state==1&&rtU.Motor_OnOff==1&&rtU.SpeedRef==1000);
    motor_td3_g431_fault_irq();assert(test_off());
    /* Independently stale bus must reject enable even when ADC stays fresh. */
    fresh(9);test_tim.BDTR=TIM_BDTR_MOE;test_tim.CCER=TIM_CCER_CC4E;
    ADC_offset=1;Vbus=24;motor_td3_g431_bus_sample();host_us+=30001;
    for(unsigned i=0;i<100;i++) motor_td3_g431_adc_sample();
    assert(!motion_begin(0,1000,.003389f,.00144f)&&test_off());
    motor_td3_telemetry t={0};uint8_t packet[192];
    t.temperature_c=NAN;t.t_us=1;
    assert(motor_td3_can_telemetry(packet,1,2,&t)==104);
    t.temperature_c=INFINITY;assert(!motor_td3_can_telemetry(packet,1,2,&t));
    t.temperature_c=NAN;t.current=NAN;assert(!motor_td3_can_telemetry(packet,1,2,&t));
    puts("{\"passed\":true,\"adapter_checks\":10}");return 0;
}
'''


def run(build, output, compiler):
    build, output = Path(build).resolve(), Path(output).resolve()
    root = Path('E:/simulink/_codex_tmp').resolve()
    if root not in output.parents:
        raise ValueError('Output must be a task directory under the approved temporary root')
    output.mkdir(parents=True, exist_ok=True)
    private = build / 'private-copy'
    own = private / 'codex-pi'
    stub = STUB.split('/* Minimum private model interface')[0] + '\n#endif\n'
    stub = stub.replace('static inline uint32_t __get_PRIMASK(void) { return 0; }',
                        'extern uint32_t test_primask;\nstatic inline uint32_t __get_PRIMASK(void) { return test_primask; }')
    stub = stub.replace('static inline void __disable_irq(void) {}',
                        'static inline void __disable_irq(void) {test_primask=1;}')
    stub = stub.replace('(void)p;test_unlock_hook();','test_primask=p;test_unlock_hook();')
    stub = stub.replace('BDTR,CCER,SR,CR1;', 'BDTR,CCER,SR,CR1,CCR1,CCR2,CCR3,EGR;')
    stub = stub.replace('uint32_t IDR;', 'uint32_t IDR,MODER,BSRR;')
    stub = stub.replace('test_gpio;', 'test_gpio,test_gpioa;')
    stub = stub.replace('#define GPIOB', '#define GPIOA (&test_gpioa)\n#define GPIOB')
    stub = stub.replace('#define TIM_SR_BIF', '#define TIM_EGR_UG 1U\n' +
                        '\n'.join(f'#define GPIO_PIN_{i} (1U<<{i})' for i in (8,9,10,13,14,15)) +
                        '\n#define TIM_SR_BIF')
    for name in ('main.h', 'fdcan.h', 'tim.h', 'stm32g431xx.h'):
        (output / name).write_text(stub, encoding='ascii')
    (output/'fuzzy_pid.h').write_text((private/'Core/Inc/fuzzy_pid.h').read_text(encoding='utf-8'),encoding='utf-8')
    host = (SKILL / 'firmware/tests/g431_adapter_host.c').read_text(encoding='utf-8')
    for line in ('ExtU rtU;\n', 'DW rtDW;\n', 'spd_kpki_type spd_kpki;\n'):
        host = host.replace(line, '')
    host = host.replace('GPIO_TypeDef test_gpio;', 'GPIO_TypeDef test_gpio,test_gpioa;')
    (output / 'adapter_host.c').write_text(host, encoding='utf-8')
    (output / 'startup_test.c').write_text(HARNESS, encoding='utf-8')
    files = [own / name for name in ('motor_td3_can.c','motor_td3_can_control.c','motor_td3_guard.c',
             'motor_td3_speedloop_pi.c','motor_td3_speedloop_pi_bind.c','motor_td3_speedloop_can.c',
             'motor_td3_speedloop_hall.c')]
    flags = ['-std=c99','-O2','-Wall','-Wextra','-ffp-contract=off','-fno-fast-math',
             '-DMOTOR_TD3_SPEEDLOOP_PI_HOST','-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC',
             '-DMOTOR_TD3_SPEEDLOOP_PI_CAN','-DMOTOR_TD3_SPEEDLOOP_PI_MOTION',
             '-DMOTOR_TD3_CAN_NO_TEMPERATURE',
             '-I'+str(output),'-I'+str(private/'MATLAB'),'-I'+str(private/'Core/Inc'),'-I'+str(own)]
    exe = output / ('startup-test.exe' if os.name == 'nt' else 'startup-test')
    args = [compiler,*flags,*map(str,files),str(private/'MATLAB/FOC_Model.c'),
            str(private/'Core/Src/fuzzy_pid.c'),str(output/'startup_test.c'),'-lm','-o',str(exe)]
    env = os.environ.copy();env.update(TEMP=str(output),TMP=str(output),TMPDIR=str(output))
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    (output/'compile.log').write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Host compilation failed; see compile.log')
    result = subprocess.run([str(exe)],env=env,capture_output=True,text=True)
    (output/'run.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Actual adapter startup check failed; see run.log')
    summary = json.loads(result.stdout)
    # Default strict decoding must remain unchanged; explicit trial opt-in only.
    packet = wire.HEADER.pack(1,0x82,0,1,2,1,0)+wire.TELEMETRY.pack(1,0,0,0,0,
             1000,0,0,0,0,24,float('nan'),.003389,.00144,0)
    packet += struct.pack('<I',zlib.crc32(packet))
    try:
        wire.unpack(packet)
        raise AssertionError('Default strict decoder accepted missing temperature')
    except wire.WireError:
        pass
    assert wire.unpack(packet,allow_missing_temperature=True)[0]['temperature_c'] is None
    rx=wire.Reassembler(allow_missing_temperature=True)
    for at in range(0,len(packet),4):
        assembled=rx.feed(bytes([0xd1,1,at//4,len(packet)])+packet[at:at+4].ljust(4,b'\0'),0)
    assert assembled==packet
    summary.update(codec_checks=3,hardware_accessed=False,
                   scope='actual motion adapter and actual generated model with host HAL substitutes')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary));return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--compiler',required=True)
    args=parser.parse_args();run(args.build,args.output,args.compiler)
