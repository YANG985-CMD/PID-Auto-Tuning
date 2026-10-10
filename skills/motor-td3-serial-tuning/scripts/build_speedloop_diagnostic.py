"""Build an audited SpeedLoop CAN diagnostic copy with GNU Arm.

No hardware access. No motion or gain-application entry point. Reject changed
private inputs. Output must be a fresh task directory under the user's temp root.
Vendor sources and binaries are local and must not be published with this skill.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from build_g431_locked_foc import digest, function, replace_once, SKILL

SOURCE_TREE_SHA256 = '4bf62e07ff571cb53ef4b6890c4daea387726eddb98d42d3022617e50a095c0b'
MODEL_SHA256 = '2e13cbff00ac51cd4510db7645a5ccf8855c5d15d468399f8f04e5516ca23e42'
MODE = 'g431-speedloop-can-diagnostic-motion-inhibited'
FILES = ('motor_td3_can.c','motor_td3_can.h','motor_td3_can_control.c','motor_td3_can_control.h',
         'motor_td3_guard.c','motor_td3_guard.h','motor_td3_protocol.h',
         'motor_td3_g431_adapter.c','motor_td3_g431_adapter.h','motor_td3_g431_off.h',
         'motor_td3_speedloop_sample.c','motor_td3_speedloop_sample.h')


def inventory(source):
    return {p.relative_to(source).as_posix():digest(p) for p in source.rglob('*')
            if p.is_file() and p.suffix.lower() in ('.c','.h','.s','.uvprojx')}


def validate_source(source):
    before=inventory(source)
    tree=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if tree!=SOURCE_TREE_SHA256:
        raise ValueError('Unaudited SpeedLoop revision; review private inputs before building')
    return before


def patch_copy(copy):
    main=copy/'Core/Src/main.c';text=main.read_text(encoding='utf-8')
    text=replace_once(text,'#include "FOC_Model.h"',
        '#include "FOC_Model.h"\n#include "motor_td3_g431_adapter.h"\n#include "motor_td3_speedloop_sample.h"')
    text=replace_once(text,'  SystemClock_Config();',
        '  SystemClock_Config();\n  FOC_Model_initialize();\n  rtU.SpeedRef=0;')
    text=replace_once(text,'  MX_TIM1_Init();',
        '  MX_TIM1_Init();\n  motor_td3_g431_disable();\n  TIM1->CR1 &= ~TIM_CR1_CEN;\n  TIM1->CCER=0;')
    text=function(text,'HAL_UART_RxCpltCallback','  (void)huart;')
    for line in ('\tHAL_UART_Receive_IT(&huart3, (uint8_t *)&aRxBuffer, 1);',
                 '\tHAL_ADCEx_InjectedStart_IT(&hadc1);','\tHAL_ADCEx_InjectedStart(&hadc2);',
                 '\tHAL_TIM_Base_Start( &htim1);','\tHAL_TIM_PWM_Start( &htim1, TIM_CHANNEL_4);'):
        text=replace_once(text,line,'')
    text=replace_once(text,'\trtU.SpeedRef = 1000;',
        '\trtU.SpeedRef=0;\n\tmotor_td3_g431_disable();')
    text=replace_once(text,'uint8_t RxData[8]={NULL};','uint8_t RxData[8]={0};')
    text=replace_once(text,'uint8_t TxData[8] = {NULL};','uint8_t TxData[8] = {0};')
    text=function(text,'HAL_GPIO_EXTI_Callback',
        '  if(GPIO_Pin==Button3_Pin) motor_td3_g431_button_stop();')
    text=function(text,'FDCAN_Config','  motor_td3_g431_init();')
    text=function(text,'HAL_ADCEx_InjectedConvCpltCallback',
        '  (void)hadc; motor_td3_g431_fault_irq(); /* Unexpected ISR: no ISR sampling configured. */')
    # Polling sample path replaces control ISR. No fuzzy gain owner or FOC step runs.
    start=text.index('\t\tHAL_ADC_Start(&hadc1);',text.index('  while (1)'))
    end=text.index('    /* USER CODE END WHILE */',start)
    text=text[:start]+'''    static uint32_t sample_due;
    motor_td3_g431_poll();
    if((int32_t)(HAL_GetTick()-sample_due)>=0) {
      sample_due=HAL_GetTick()+10U;
      motor_td3_speedloop_sample();
    }
'''+text[end:]
    for line in ('\t\tHallThetaAdd = (PI/3)/(HallTemp/3200000)/10000;\n',
                 '\t\tHallSpeed = (PI/3)/(HallTemp/3200000)*30/(2*PI);\n'):
        text=replace_once(text,line,'')
    text=replace_once(text,'\t\tHallReadTemp |= HAL_GPIO_ReadPin(GPIOB,GPIO_PIN_6)<<2;',
        '''\t\tHallReadTemp |= HAL_GPIO_ReadPin(GPIOB,GPIO_PIN_6)<<2;
        if(!motor_td3_g431_hall_capture((uint32_t)HallTemp,HallReadTemp)) return;
        HallThetaAdd=0; /* No 10 kHz control integration in diagnostic mode. */
        HallSpeed=(PI/3)/(HallTemp/3200000)*30/(2*PI);''')
    text=replace_once(text,'  __disable_irq();','  motor_td3_g431_disable();\n  __disable_irq();')
    main.write_text(text,encoding='utf-8',newline='\n')
    if re.search(r'HAL_TIM(?:Ex)?_(?:PWMN?|Base)_Start\s*\(',text) or 'FOC_Model_step();' in text:
        raise ValueError('Unexpected timer start or control step in diagnostic copy')
    adc=copy/'Core/Src/adc.c';text=adc.read_text(encoding='utf-8')
    for old,new in (('ADC_EXTERNALTRIGINJEC_T1_CC4','ADC_INJECTED_SOFTWARE_START'),
                    ('ADC_EXTERNALTRIGINJECCONV_EDGE_RISING','ADC_EXTERNALTRIGINJECCONV_EDGE_NONE'),
                    ('ADC_EOC_SINGLE_CONV','ADC_EOC_SEQ_CONV')):
        if text.count(old)!=2: raise ValueError('Unexpected ADC configuration: '+old)
        text=text.replace(old,new)
    adc.write_text(text,encoding='utf-8',newline='\n')
    it=copy/'Core/Src/stm32g4xx_it.c';text=it.read_text(encoding='utf-8')
    text=replace_once(text,'#include "FOC_Model.h"','#include "FOC_Model.h"\n#include "motor_td3_g431_adapter.h"')
    text=replace_once(text,'  HAL_IncTick();','  HAL_IncTick();\n  motor_td3_g431_tick_1ms();')
    text=replace_once(text,'\tHAL_FDCAN_GetRxMessage(&hfdcan1,FDCAN_RX_FIFO0,&RxHeader,RxData);','')
    for name in ('NMI_Handler','HardFault_Handler','MemManage_Handler','BusFault_Handler','UsageFault_Handler'):
        text=function(text,name,'  motor_td3_g431_disable();\n  while(1) {}')
    text=replace_once(text,'  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */',
        '  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */\n  motor_td3_g431_fault_irq();')
    it.write_text(text,encoding='utf-8',newline='\n')
    fdcan=copy/'Core/Src/fdcan.c';text=fdcan.read_text(encoding='utf-8')
    text=replace_once(text,'hfdcan1.Init.ExtFiltersNbr = 1;','hfdcan1.Init.ExtFiltersNbr = 0;')
    fdcan.write_text(text,encoding='utf-8',newline='\n')
    if digest(copy/'MATLAB/FOC_Model.c')!=MODEL_SHA256: raise ValueError('Generated model changed')


def startup_from_vectors(keil):
    # Extract order from the hash-verified vendor vector table, rather than invent
    # interrupt positions. GNU reset initializes .data/.bss and the C runtime.
    section=keil.split('__Vectors       DCD',1)[1].split('\n__Vectors_End',1)[0]
    vectors=['_estack']+re.findall(r'^\s+DCD\s+(\w+)',section,re.M)
    if len(vectors)!=118 or vectors[1]!='Reset_Handler':
        raise ValueError('Unexpected vendor vector table layout')
    prefix='''.syntax unified
.cpu cortex-m4
.fpu fpv4-sp-d16
.thumb
.section .isr_vector,"a",%progbits
.global __Vectors
__Vectors:
'''
    prefix+=''.join('.word '+v+'\n' for v in vectors)
    prefix+='''.section .text.Reset_Handler,"ax",%progbits
.global Reset_Handler
.type Reset_Handler,%function
.thumb_func
Reset_Handler:
  bl SystemInit
  ldr r0, =_sidata
  ldr r1, =_sdata
  ldr r2, =_edata
1: cmp r1, r2
  bcs 2f
  ldr r3, [r0], #4
  str r3, [r1], #4
  b 1b
2: ldr r1, =_sbss
  ldr r2, =_ebss
  movs r3, #0
3: cmp r1, r2
  bcs 4f
  str r3, [r1], #4
  b 3b
4: bl __libc_init_array
  bl main
  b Default_Handler
.size Reset_Handler, .-Reset_Handler
.section .text.Default_Handler,"ax",%progbits
.global Default_Handler
.type Default_Handler,%function
.thumb_func
Default_Handler:
  bl motor_td3_g431_disable
  cpsid i
5: b 5b
.size Default_Handler, .-Default_Handler
'''
    for v in sorted(set(vectors[2:])-{'0'}):
        prefix+='.weak '+v+'\n.thumb_set '+v+', Default_Handler\n'
    prefix+='.section .text._init,"ax",%progbits\n.global _init\n.thumb_func\n_init:\n bx lr\n'
    return prefix


LINKER='''ENTRY(Reset_Handler)
MEMORY { FLASH(rx): ORIGIN = 0x08000000, LENGTH = 128K
         RAM(xrw): ORIGIN = 0x20000000, LENGTH = 32K }
_estack = ORIGIN(RAM) + LENGTH(RAM);
SECTIONS {
 .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
 .text : { *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini)) . = ALIGN(4); } > FLASH
 .ARM.extab : { *(.ARM.extab*) } > FLASH
 .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > FLASH
 .preinit_array : { PROVIDE_HIDDEN(__preinit_array_start = .); KEEP(*(.preinit_array*)) PROVIDE_HIDDEN(__preinit_array_end = .); } > FLASH
 .init_array : { PROVIDE_HIDDEN(__init_array_start = .); KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array*)) PROVIDE_HIDDEN(__init_array_end = .); } > FLASH
 .fini_array : { PROVIDE_HIDDEN(__fini_array_start = .); KEEP(*(SORT(.fini_array.*))) KEEP(*(.fini_array*)) PROVIDE_HIDDEN(__fini_array_end = .); } > FLASH
 _sidata = LOADADDR(.data);
 .data : { . = ALIGN(4); _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT> FLASH
 .bss (NOLOAD) : { . = ALIGN(8); _sbss = .; *(.bss*) *(COMMON) . = ALIGN(8); _ebss = .; } > RAM
 _end = .; end = .;
 .reserve (NOLOAD) : { . = ALIGN(8); . = . + 0x200; . = . + 0x1000; } > RAM
 ASSERT(. <= _estack, "RAM overlaps reserved heap and 4KB stack")
}
'''


def build(args):
    source=Path(args.source).resolve();out=Path(args.output).resolve();arm=Path(args.arm_bin).resolve()
    temp=Path(args.temp_root).resolve()
    if temp not in out.parents or source in out.parents or out in source.parents:
        raise ValueError('Use a separate task directory under temp-root')
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh empty task directory')
    before=validate_source(source)
    project=source/'MDK-ARM/STM32G4_GPIO.uvprojx';sources=[]
    for elem in ET.parse(project).findall('.//FilePath'):
        p=(project.parent/elem.text.replace('\\','/')).resolve()
        if source not in p.parents: raise ValueError('Project source reference escapes tree')
        if p.suffix.lower() in ('.c','.s'): sources.append(p.relative_to(source))
    if len(sources)!=42 or sources[0].suffix.lower()!='.s':
        raise ValueError('Audited SpeedLoop translation units changed')
    out.mkdir(parents=True,exist_ok=True);copy=out/'private-copy';copy.mkdir()
    for folder in ('Core','Drivers','MATLAB','Middlewares/ST/ARM/DSP/Inc'):
        shutil.copytree(source/folder,copy/folder,ignore=shutil.ignore_patterns('*.o','*.d','*.axf','*.hex','*.bak'))
    patch_copy(copy)
    startup=out/'startup.S';startup.write_text(startup_from_vectors((source/sources[0]).read_text(encoding='utf-8')),encoding='ascii')
    linker=out/'diagnostic.ld';linker.write_text(LINKER,encoding='ascii')
    ours=copy/'codex-can';ours.mkdir()
    for name in FILES: shutil.copy2(SKILL/'firmware'/name,ours/name)
    sources.extend(Path('codex-can')/name for name in FILES if name.endswith('.c'))
    includes=[copy/p for p in ('Core/Inc','Drivers/STM32G4xx_HAL_Driver/Inc',
        'Drivers/STM32G4xx_HAL_Driver/Inc/Legacy','Drivers/CMSIS/Device/ST/STM32G4xx/Include',
        'Drivers/CMSIS/Include','Middlewares/ST/ARM/DSP/Inc','MATLAB','codex-can')]
    suffix='.exe' if os.name=='nt' else ''
    def tool(name): return arm/('arm-none-eabi-'+name+suffix)
    logs=[]
    environment=os.environ.copy()
    environment.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    def run(argv):
        r=subprocess.run([str(x) for x in argv],cwd=out,env=environment,capture_output=True,text=True)
        logs.append(r.stdout+r.stderr);(out/'build.log').write_text('\n'.join(logs),encoding='utf-8')
        if r.returncode: raise RuntimeError('Build failed; inspect build.log')
        return r.stdout
    version=run([tool('gcc'),'--version']).splitlines()[0]
    flags=['-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16','-mfloat-abi=hard',
           '-std=gnu99','-O2','-g','-pipe','-ffunction-sections','-fdata-sections','-ffp-contract=off','-fno-fast-math',
           '-DSTM32G431xx','-DUSE_HAL_DRIVER','-DARM_MATH_CM4','-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC',
           '-Wall','-Wextra']
    objects=[]
    for i,p in enumerate(sources):
        obj=out/(f'{i:02d}_'+p.stem+'.o');objects.append(obj)
        inp=startup if i==0 else copy/p
        unit_flags=flags+(['-Werror'] if p.parts[0]=='codex-can' else [])
        run([tool('gcc'),*unit_flags,*['-I'+str(d) for d in includes],'-c',inp,'-o',obj])
    elf=out/'speedloop-diagnostic.elf'
    run([tool('gcc'),*flags,'-nostartfiles','--specs=nano.specs','--specs=nosys.specs',
         '-T',linker,'-Wl,--gc-sections','-Wl,-Map='+str(out/'image.map'),'-o',elf,*objects,'-lm'])
    for fmt,ext in (('ihex','hex'),('binary','bin')):
        run([tool('objcopy'),'-O',fmt,elf,out/('speedloop-diagnostic.'+ext)])
    symbols={}
    for line in run([tool('nm'),'--defined-only',elf]).splitlines():
        match=re.fullmatch(r'([0-9a-fA-F]+)\s+\w\s+(\S+)',line)
        if match: symbols[match[2]]=int(match[1],16)
    forbidden={'HAL_TIM_PWM_Start','HAL_TIMEx_PWMN_Start','HAL_TIM_Base_Start','FOC_Model_step','FuzzyPID_Compute'}
    if forbidden.intersection(symbols):
        raise ValueError('Motion/control entry point survived diagnostic link: '+str(sorted(forbidden.intersection(symbols))))
    blob=(out/'speedloop-diagnostic.bin').read_bytes();sp,entry=struct.unpack('<II',blob[:8])
    if sp!=0x20008000 or not (entry&1 and 0x08000000<=entry<0x08020000) or len(blob)>0x20000:
        raise ValueError('Image vectors/size outside G431 128KB/32KB map')
    size=run([tool('size'),elf]).strip()
    if inventory(source)!=before: raise RuntimeError('Private source changed during build')
    summary=dict(schema_version=1,mode=MODE,firmware_id='g431-speedloop-diag-v1',
        compiler=version,translation_units=len(sources),source_files_unchanged=True,source_files_checked=len(before),
        source_tree_sha256=SOURCE_TREE_SHA256,model_sha256=MODEL_SHA256,model_executed=False,
        hardware_executed=False,flash_programming=False,capabilities=0,motion_enable_implemented=False,
        gain_application_implemented=False,temperature_sensor_implemented=False,production_boot_identity_implemented=False,
        adc_trigger='software; complete injected sequences, nominal 100Hz; sequential ADC1/ADC2',
        foc_sampling_preserved=False,forbidden_motion_symbols_absent=True,image_bytes=len(blob),elf_sha256=digest(elf),
        bin_sha256=digest(out/'speedloop-diagnostic.bin'),hex_sha256=digest(out/'speedloop-diagnostic.hex'),
        initial_sp=sp,entry=entry,size_report=size,symbols=symbols,
        integration_sha256={name:digest(ours/name) for name in FILES})
    (out/'build-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return {k:v for k,v in summary.items() if k!='symbols'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','arm-bin','output'): p.add_argument('--'+name,required=True)
    p.add_argument('--temp-root',default=r'E:\simulink\_codex_tmp')
    print(json.dumps(build(p.parse_args()),indent=2))


if __name__=='__main__': main()
