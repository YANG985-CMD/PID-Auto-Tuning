"""Build the user's hash-audited 17.SpeedLoop as one USER3-started 3s trial.
No hardware access. Private vendor source and linked binaries remain local.
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from build_speedloop_diagnostic import validate_source, inventory, startup_from_vectors, LINKER, MODEL_SHA256
from build_g431_locked_foc import digest, function, replace_once, SKILL

FILES=('motor_td3_speedloop_baseline.c','motor_td3_speedloop_baseline.h')


def patch(copy):
    main=copy/'Core/Src/main.c';t=main.read_text(encoding='utf-8')
    t=replace_once(t,'#include "FOC_Model.h"','#include "FOC_Model.h"\n#include "motor_td3_speedloop_baseline.h"')
    t=replace_once(t,'  HAL_Init();','  if(!motor_td3_baseline_boot()) while(1) { motor_td3_baseline_off(); }\n  HAL_Init();')
    t=replace_once(t,'  MX_TIM1_Init();','  MX_TIM1_Init();\n  motor_td3_baseline_off();')
    begin=t.index('  /* USER CODE BEGIN 2 */');end=t.index('  /* USER CODE END 2 */',begin)
    t=t[:begin]+'''  /* USER CODE BEGIN 2 */
    FOC_Model_initialize();
    FuzzyPID_Init(&fuzzy_speed_pid,0.003389f,0.00144f,0.0f,500.0f,100.0f);
    rtU.SpeedRef=1000;rtU.v_bus=24.0f;
    HAL_OPAMP_Start(&hopamp1);HAL_OPAMP_Start(&hopamp2);HAL_OPAMP_Start(&hopamp3);
    HAL_ADCEx_Calibration_Start(&hadc1,ADC_SINGLE_ENDED);
    HAL_ADCEx_Calibration_Start(&hadc2,ADC_SINGLE_ENDED);
    HAL_DAC_SetValue(&hdac3,DAC_CHANNEL_1,DAC_ALIGN_12B_R,3000);
    HAL_DAC_Start(&hdac3,DAC_CHANNEL_1);HAL_DAC_Start(&hdac1,DAC_CHANNEL_1);
    HAL_COMP_Start(&hcomp1);
    HAL_TIMEx_HallSensor_Start_IT(&htim4);
    FDCAN_Config();
    motor_td3_baseline_off();
    __HAL_TIM_CLEAR_FLAG(&htim1,TIM_FLAG_BREAK|TIM_FLAG_BREAK2|TIM_FLAG_SYSTEM_BREAK);
    __HAL_ADC_CLEAR_FLAG(&hadc1,ADC_FLAG_JEOC|ADC_FLAG_EOC);
    __HAL_ADC_CLEAR_FLAG(&hadc2,ADC_FLAG_JEOC|ADC_FLAG_EOC);
    HAL_ADCEx_InjectedStart_IT(&hadc1);HAL_ADCEx_InjectedStart(&hadc2);
    TIM1->ARR=7999;TIM1->CCR4=7998;
    HAL_TIM_Base_Start(&htim1);HAL_TIM_PWM_Start(&htim1,TIM_CHANNEL_4);
    motor_td3_baseline_init();
'''+t[end:]
    start=t.index('\t\tHAL_ADC_Start(&hadc1);',t.index('  while (1)'))
    end=t.index('    /* USER CODE END WHILE */',start)
    t=t[:start]+'''    static uint32_t bus_due;
    motor_td3_baseline_poll();
    if((int32_t)(HAL_GetTick()-bus_due)>=0) {
      bus_due=HAL_GetTick()+5U;
      if(HAL_ADC_Start(&hadc1)==HAL_OK && HAL_ADC_Start(&hadc2)==HAL_OK &&
         HAL_ADC_PollForConversion(&hadc1,1)==HAL_OK && HAL_ADC_PollForConversion(&hadc2,1)==HAL_OK) {
        Vpoten=HAL_ADC_GetValue(&hadc1);adc_vbus=HAL_ADC_GetValue(&hadc2);
        Vbus=adc_vbus*3.3f/4096*26;
        /* Avoid dividing by zero during unpowered idle; physical bus remains in the record and start gate. */
        rtU.v_bus=Vbus>1.0f?Vbus:24.0f;
      }
      /* A regular conversion can be busy while the reference injected group
       * is servicing the FOC step. Retain the last valid bus sample instead
       * of turning HAL_BUSY into an ADC fault. */
      motor_td3_baseline_bus_updated();
    }
'''+t[end:]
    t=function(t,'HAL_GPIO_EXTI_Callback','  if(GPIO_Pin==Button3_Pin) motor_td3_baseline_button();')
    t=function(t,'HAL_UART_RxCpltCallback','  (void)huart; /* No remote start or tuning commands. */')
    t=function(t,'FDCAN_Config','  motor_td3_baseline_can_init();')
    t=replace_once(t,'uint8_t RxData[8]={NULL};','uint8_t RxData[8]={0};')
    t=replace_once(t,'uint8_t TxData[8] = {NULL};','uint8_t TxData[8] = {0};')
    t=replace_once(t,'\t\tif(ADC_offset == 0)','\t\tmotor_td3_baseline_adc();\n\t\tif(ADC_offset == 0)')
    t=replace_once(t,'\t\t\tFOC_Model_step();','\t\t\tFOC_Model_step();\n\t\t\tmotor_td3_baseline_after_step();')
    t=replace_once(t,'\t\t\tHAL_UART_Transmit_DMA(&huart3,(uint8_t *)tempData,6*4);','')
    # Validate Hall state before the original period division. Preserve its mapping.
    line='\t\tHallTemp = HAL_TIM_ReadCapturedValue(&htim4,TIM_CHANNEL_1);;'
    t=replace_once(t,line,line+'\n\t\tif(!motor_td3_baseline_hall((uint32_t)HallTemp,(GPIOB->IDR>>6)&7U)) return;')
    t=replace_once(t,'  __disable_irq();','  motor_td3_baseline_fault(11);\n  __disable_irq();')
    main.write_text(t,encoding='utf-8',newline='\n')
    if 'HAL_TIMEx_PWMN_Start' in t: raise ValueError('Sequential phase start survived')
    it=copy/'Core/Src/stm32g4xx_it.c';t=it.read_text(encoding='utf-8')
    t=replace_once(t,'#include "FOC_Model.h"','#include "FOC_Model.h"\n#include "motor_td3_speedloop_baseline.h"')
    t=replace_once(t,'  HAL_IncTick();','  HAL_IncTick();\n  motor_td3_baseline_tick();')
    t=replace_once(t,'\tHAL_FDCAN_GetRxMessage(&hfdcan1,FDCAN_RX_FIFO0,&RxHeader,RxData);','')
    t=replace_once(t,'  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */','  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */\n  motor_td3_baseline_fault(1);')
    for name in ('NMI_Handler','HardFault_Handler','MemManage_Handler','BusFault_Handler','UsageFault_Handler'):
        t=function(t,name,'  motor_td3_baseline_fault(11);\n  while(1) {}')
    it.write_text(t,encoding='utf-8',newline='\n')
    p=copy/'Core/Src/fdcan.c';t=p.read_text(encoding='utf-8')
    t=replace_once(t,'hfdcan1.Init.ExtFiltersNbr = 1;','hfdcan1.Init.ExtFiltersNbr = 0;')
    t=replace_once(t,'hfdcan1.Init.AutoRetransmission = DISABLE;','hfdcan1.Init.AutoRetransmission = ENABLE;')
    p.write_text(t,encoding='utf-8',newline='\n')


def build(a):
    source=Path(a.source).resolve();out=Path(a.output).resolve();arm=Path(a.arm_bin).resolve()
    root=Path(a.temp_root).resolve()
    if root not in out.parents or source in out.parents or out in source.parents: raise ValueError('Invalid task output')
    if out.exists() and any(out.iterdir()): raise ValueError('Use fresh output')
    before=validate_source(source);project=source/'MDK-ARM/STM32G4_GPIO.uvprojx';units=[]
    for e in ET.parse(project).findall('.//FilePath'):
        p=(project.parent/e.text.replace('\\','/')).resolve()
        if source not in p.parents: raise ValueError('Source outside project')
        if p.suffix.lower() in ('.c','.s'): units.append(p.relative_to(source))
    if len(units)!=42 or units[0].suffix.lower()!='.s': raise ValueError('Source units changed')
    out.mkdir(parents=True,exist_ok=True);copy=out/'private-copy';copy.mkdir()
    for name in ('Core','Drivers','MATLAB','Middlewares/ST/ARM/DSP/Inc'):
        shutil.copytree(source/name,copy/name,ignore=shutil.ignore_patterns('*.o','*.d','*.axf','*.hex','*.bak'))
    patch(copy);own=copy/'codex-baseline';own.mkdir()
    for name in FILES: shutil.copy2(SKILL/'firmware'/name,own/name)
    startup=out/'startup.S';startup.write_text(startup_from_vectors((source/units[0]).read_text(encoding='utf-8')).replace(
        'bl motor_td3_g431_disable','bl motor_td3_baseline_off'),encoding='ascii')
    linker=out/'image.ld';linker.write_text(LINKER,encoding='ascii')
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out));logs=[]
    def run(cmd):
        r=subprocess.run([str(x) for x in cmd],cwd=out,env=env,capture_output=True,text=True)
        logs.append(r.stdout+r.stderr);(out/'build.log').write_text('\n'.join(logs),encoding='utf-8')
        if r.returncode: raise RuntimeError('Build failed: inspect build.log')
        return r.stdout
    suffix='.exe' if os.name=='nt' else ''
    def tool(n): return arm/('arm-none-eabi-'+n+suffix)
    flags=['-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-std=gnu99','-O2','-g','-pipe',
        '-ffunction-sections','-fdata-sections','-ffp-contract=off','-fno-fast-math','-DSTM32G431xx','-DUSE_HAL_DRIVER',
        '-DARM_MATH_CM4','-Wall','-Wextra']
    includes=[copy/p for p in ('Core/Inc','Drivers/STM32G4xx_HAL_Driver/Inc','Drivers/STM32G4xx_HAL_Driver/Inc/Legacy',
        'Drivers/CMSIS/Device/ST/STM32G4xx/Include','Drivers/CMSIS/Include','Middlewares/ST/ARM/DSP/Inc','MATLAB','codex-baseline')]
    units.append(Path('codex-baseline/motor_td3_speedloop_baseline.c'));objects=[]
    for i,p in enumerate(units):
        obj=out/(f'{i:02d}_'+p.stem+'.o');objects.append(obj)
        run([tool('gcc'),*flags,*(['-Werror'] if p.parts[0]=='codex-baseline' else []),
            *['-I'+str(d) for d in includes],'-c',startup if i==0 else copy/p,'-o',obj])
    elf=out/'speedloop-baseline.elf'
    run([tool('gcc'),*flags,'-nostartfiles','--specs=nano.specs','--specs=nosys.specs','-T',linker,
        '-Wl,--gc-sections','-Wl,--undefined=motor_td3_baseline_build_id','-Wl,-Map='+str(out/'image.map'),'-o',elf,*objects,'-lm'])
    for fmt,ext in (('binary','bin'),('ihex','hex')): run([tool('objcopy'),'-O',fmt,elf,out/('speedloop-baseline.'+ext)])
    symbols={}
    for line in run([tool('nm'),'--defined-only',elf]).splitlines():
        fields=line.split()
        if len(fields)==3:
            try: symbols[fields[2]]=int(fields[0],16)
            except ValueError: pass
    blob=(out/'speedloop-baseline.bin').read_bytes();sp,pc=struct.unpack_from('<II',blob)
    if sp!=0x20008000 or not(pc&1 and 0x08000000<=pc<0x08020000) or len(blob)>131072: raise ValueError('Image layout')
    if inventory(source)!=before or digest(copy/'MATLAB/FOC_Model.c')!=MODEL_SHA256: raise ValueError('Original control changed')
    m=dict(build_id='g431-speedloop-baseline-3s-v1',binary_bytes=len(blob),bin_sha256=digest(out/'speedloop-baseline.bin'),
        hex_sha256=digest(out/'speedloop-baseline.hex'),translation_units=len(units),symbols=symbols,
        own_source_sha256={n:digest(own/n) for n in FILES},source_unchanged=True,generated_model_unchanged=True,
        trial_duration_ms=3000,speed_ref_rpm=1000,actor_connected=False,td3_gains_enabled=False,
        measured_current_calibration=False,temperature_sensor=False,validated_thermal_limits=None,
        hardware_accessed=False,flash_programmed=False)
    (out/'build-summary.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in m.items() if k not in ('symbols','own_source_sha256')}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'): p.add_argument('--'+name,required=True)
    p.add_argument('--temp-root',default='E:/simulink/_codex_tmp');build(p.parse_args())
