"""Build a motion-inhibited CAN integration copy of the audited private FOC example.

No probe, Flash, serial or CAN access. Vendor files remain local; nothing in the
source directory is changed. Output MUST be an empty task temporary directory.
Unknown revisions are rejected before any output or compilation.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SOURCE_TREE_SHA256 = '64c32a931909146761cd1fcf0d0613bc72be3bae5100d193feb43fdb98be5f5f'
AUDITED = {
    'Core/Src/main.c': '56b956801b91f201a8df7dac79b2b34364e474970bd73c282281217468f2d0b0',
    'Core/Src/stm32g4xx_it.c': 'e0482b666ccc4b2d4425db4794e78c8685b9442a4082c64b365b02e7fe847914',
    'Core/Src/fdcan.c': '8baf008c83ae75445c76b509d8c2643b331646ef89a9265c785fca5e77c0794a',
    'Core/Src/tim.c': '0c70c06cd48f315445dcb8e0d56c71665af9764e0626c5dbce29bb4e48cb4d44',
    'Core/Src/comp.c': '0b1b61006ee93beae69641402b8c8f1fad76917cb329809cf54f545234b81c6d',
    'MATLAB/FOC_Model.c': 'bc807df122f02cd70bc811d65aae1cd07fc1aaa3b56f0eecf35842e1680afc5b',
    'MATLAB/FOC_Model.h': 'd2b8325b1887945244ff554dde62fa15b16a823ee7388f746eb8c85097232745',
    'MDK-ARM/startup_stm32g431xx.s': 'cbff8c2ad962bd4b5ab562cd855482c07b74894dd992c7b03a6682fb589eea3b',
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Private source anchor missing or repeated: ' + old[:65])
    return text.replace(old, new, 1)

def function(text, name, body):
    # Used only on hash-verified sources. Function declarations are not matched.
    match = re.search(r'void\s+' + re.escape(name) + r'\([^;{}]*\)\s*\{', text)
    if not match:
        raise ValueError('Missing function ' + name)
    start, pos, depth = match.end()-1, match.end(), 1
    while depth:
        if pos >= len(text): raise ValueError('Unterminated function ' + name)
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[:start] + '{\n' + body + '\n}' + text[pos:]

def patch_copy(copy):
    main = copy/'Core/Src/main.c'
    text = main.read_text(encoding='utf-8')
    text = replace_once(text, '#include "FOC_Model.h"', '#include "FOC_Model.h"\n#include "motor_td3_g431_adapter.h"\n#include <math.h>')
    text = function(text, 'HAL_GPIO_EXTI_Callback', '  if(GPIO_Pin==Button3_Pin) motor_td3_g431_button_stop();')
    text = function(text, 'FDCAN_Config', '  motor_td3_g431_init();')
    # Remove the UART input owner and DMA telemetry from the high-frequency ISR.
    text = function(text, 'HAL_UART_RxCpltCallback', '  (void)huart; /* CAN diagnostic build: no UART command owner. */')
    text = replace_once(text, '\tHAL_UART_Receive_IT(&huart3, (uint8_t *)&aRxBuffer, 1);', '')
    text = replace_once(text, '\t\t\tHAL_UART_Transmit_DMA(&huart3,(uint8_t *)tempData,6*4);', '')
    text = replace_once(text, '\tFOC_Model_initialize();\n\trtU.SpeedRef = 1000;', '')
    text = replace_once(text, '  MX_TIM1_Init();', '  MX_TIM1_Init();\n  motor_td3_g431_disable();')
    text = replace_once(text, '  MX_TIM4_Init();', '  MX_TIM4_Init();\n  FOC_Model_initialize();\n  rtU.SpeedRef=0;\n  motor_td3_g431_disable();')
    text = replace_once(text, '\tHAL_TIM_PWM_Start( &htim1, TIM_CHANNEL_4);', '\tHAL_TIM_PWM_Start( &htim1, TIM_CHANNEL_4);\n\tmotor_td3_g431_disable();')
    start = text.index('\t\tHAL_ADC_Start(&hadc1);', text.index('  while (1)'))
    end = text.index('    /* USER CODE END WHILE */', start)
    text = text[:start] + '''    static uint32_t bus_due;
    motor_td3_g431_poll();
    if((int32_t)(HAL_GetTick()-bus_due)>=0) {
      bus_due=HAL_GetTick()+10U;
      if(HAL_ADC_Start(&hadc1)!=HAL_OK || HAL_ADC_Start(&hadc2)!=HAL_OK ||
         HAL_ADC_PollForConversion(&hadc1,1)!=HAL_OK || HAL_ADC_PollForConversion(&hadc2,1)!=HAL_OK) {
        Vbus=NAN; rtU.v_bus=NAN; motor_td3_g431_fault_irq();
      } else {
        Vpoten=HAL_ADC_GetValue(&hadc1);adc_vbus=HAL_ADC_GetValue(&hadc2);
        Vbus=adc_vbus*3.3f/4096*26;rtU.v_bus=Vbus;
      }
    }
''' + text[end:]
    text = replace_once(text, '\t\t\tFOC_Model_step();', '''            motor_td3_g431_adc_sample();
            if(isfinite(rtU.v_bus) && rtU.v_bus>0.0F) FOC_Model_step();
            else { rtY.tABC[0]=0;rtY.tABC[1]=0;rtY.tABC[2]=0; }''')
    # Validate capture BEFORE division. Original angle and speed mapping retained.
    for line in ('\t\tHallThetaAdd = (PI/3)/(HallTemp/3200000)/10000;\n',
                 '\t\tHallSpeed = (PI/3)/(HallTemp/3200000)*30/(2*PI);\n'):
        text = replace_once(text,line,'')
    text = replace_once(text, '\t\tHallReadTemp |= HAL_GPIO_ReadPin(GPIOB,GPIO_PIN_6)<<2;', '''\t\tHallReadTemp |= HAL_GPIO_ReadPin(GPIOB,GPIO_PIN_6)<<2;
        if(!motor_td3_g431_hall_capture((uint32_t)HallTemp,HallReadTemp)) return;
        HallThetaAdd=(PI/3)/(HallTemp/3200000)/10000;
        HallSpeed=(PI/3)/(HallTemp/3200000)*30/(2*PI);''')
    text = replace_once(text, '  __disable_irq();', '  motor_td3_g431_disable();\n  __disable_irq();')
    main.write_text(text,encoding='utf-8',newline='\n')
    it = copy/'Core/Src/stm32g4xx_it.c'; text = it.read_text(encoding='utf-8')
    text = replace_once(text,'#include "FOC_Model.h"','#include "FOC_Model.h"\n#include "motor_td3_g431_adapter.h"')
    text = replace_once(text,'  HAL_IncTick();','  HAL_IncTick();\n  motor_td3_g431_tick_1ms();')
    text = replace_once(text,'\tHAL_FDCAN_GetRxMessage(&hfdcan1,FDCAN_RX_FIFO0,&RxHeader,RxData);','')
    for name in ('NMI_Handler','HardFault_Handler','MemManage_Handler','BusFault_Handler','UsageFault_Handler'):
        text = function(text,name,'  motor_td3_g431_disable();\n  while(1) {}')
    text = replace_once(text,'  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */','  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */\n  motor_td3_g431_fault_irq();')
    it.write_text(text,encoding='utf-8',newline='\n')
    fdcan=copy/'Core/Src/fdcan.c';text=fdcan.read_text(encoding='utf-8')
    fdcan.write_text(replace_once(text,'hfdcan1.Init.ExtFiltersNbr = 1;','hfdcan1.Init.ExtFiltersNbr = 0;'),encoding='utf-8',newline='\n')
    startup=copy/'MDK-ARM/startup_stm32g431xx.s';text=startup.read_text(encoding='utf-8')
    startup.write_text(replace_once(text,'Stack_Size\t\tEQU     0x400','Stack_Size\t\tEQU     0x1000'),encoding='utf-8',newline='\n')
    # Static build gate: there must be no remaining physical phase start call.
    if re.search(r'HAL_TIM(?:Ex)?_PWMN?_Start\s*\([^;]*TIM_CHANNEL_[123]\b',main.read_text(encoding='utf-8')):
        raise ValueError('Unexpected motor PWM start call in locked copy')
    if digest(copy/'MATLAB/FOC_Model.c')!=AUDITED['MATLAB/FOC_Model.c']:
        raise ValueError('Generated controller changed')

def build(args):
    source=Path(args.source).resolve();out=Path(args.output).resolve();arm=Path(args.arm_bin).resolve()
    if out==source or source in out.parents or out in source.parents:
        raise ValueError('Output must be separate from the private source tree')
    for name,value in AUDITED.items():
        if digest(source/name)!=value: raise ValueError('Unaudited source revision: '+name)
    before={p.relative_to(source).as_posix():digest(p) for p in source.rglob('*')
            if p.is_file() and p.suffix.lower() in ('.c','.h','.s','.uvprojx')}
    tree_hash=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    if tree_hash!=SOURCE_TREE_SHA256: raise ValueError('Unaudited project/header/source tree; review revision before rebuilding')
    xml=ET.parse(source/'MDK-ARM/STM32G4_GPIO.uvprojx')
    sources=[]
    for elem in xml.findall('.//FilePath'):
        name=elem.text.replace('\\','/')
        path=(source/'MDK-ARM'/name).resolve()
        if source not in path.parents: raise ValueError('Project reference escapes source tree')
        if path.suffix.lower() in ('.c','.s'): sources.append(path.relative_to(source))
    if not sources: raise ValueError('No project sources')
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh empty task output')
    out.mkdir(parents=True,exist_ok=True);copy=out/'private-copy';copy.mkdir()
    for folder in ('Core','Drivers','MATLAB'):
        shutil.copytree(source/folder,copy/folder,ignore=shutil.ignore_patterns('*.o','*.d','*.axf','*.hex','*.bak'))
    for folder in ('Middlewares/ST/ARM/DSP/Inc',):
        shutil.copytree(source/folder,copy/folder)
    (copy/'MDK-ARM').mkdir()
    shutil.copy2(source/'MDK-ARM/startup_stm32g431xx.s',copy/'MDK-ARM/startup_stm32g431xx.s')
    patch_copy(copy)
    ours=copy/'codex-can';ours.mkdir()
    for name in ('motor_td3_can.c','motor_td3_can.h','motor_td3_can_control.c','motor_td3_can_control.h',
                 'motor_td3_guard.c','motor_td3_guard.h','motor_td3_protocol.h',
                 'motor_td3_g431_adapter.c','motor_td3_g431_adapter.h','motor_td3_g431_off.h'):
        shutil.copy2(SKILL/'firmware'/name,ours/name)
    sources.extend(Path('codex-can')/name for name in ('motor_td3_can.c','motor_td3_can_control.c','motor_td3_guard.c','motor_td3_g431_adapter.c'))
    includes=[copy/p for p in ('Core/Inc','Drivers/STM32G4xx_HAL_Driver/Inc','Drivers/STM32G4xx_HAL_Driver/Inc/Legacy',
        'Drivers/CMSIS/Device/ST/STM32G4xx/Include','Drivers/CMSIS/Include','Middlewares/ST/ARM/DSP/Inc','MATLAB','codex-can')]
    logs=[];objects=[]
    def command(argv):
        result=subprocess.run([str(x) for x in argv],cwd=out,capture_output=True,text=True)
        logs.append(result.stdout+result.stderr);(out/'build.log').write_text('\n'.join(logs),encoding='utf-8')
        if result.returncode: raise RuntimeError('Full FOC build failed; inspect build.log')
    for index,path in enumerate(sources):
        obj=out/(f'{index:02d}_'+path.stem+'.o');objects.append(obj)
        if path.suffix.lower()=='.s':
            command([arm/'armasm.exe','--cpu=Cortex-M4.fp','--apcs=interwork','--debug','-o',obj,copy/path])
        else:
            flags=['--target=arm-arm-none-eabi','-mcpu=cortex-m4','-mfpu=fpv4-sp-d16','-mfloat-abi=hard',
                '-std=gnu99','-O2','-g','-ffunction-sections','-fdata-sections','-ffp-contract=off','-fno-fast-math',
                '-DSTM32G431xx','-DUSE_HAL_DRIVER','-DARM_MATH_CM4','-Wall','-Wextra']
            if path.parts[0]=='codex-can': flags.append('-Werror')
            command([arm/'armclang.exe',*flags,*[v for p in includes for v in ('-I',p)],'-c',copy/path,'-o',obj])
    startup_obj=objects[0]
    if sources[0].suffix.lower()!='.s': raise ValueError('Startup object order changed')
    scatter=out/'locked.sct'
    scatter.write_text(f'''LR_IROM1 0x08000000 0x20000 {{
 ER_IROM1 0x08000000 0x20000 {{
  {startup_obj.name} (RESET, +First)
  *(InRoot$$Sections)
  .ANY (+RO)
 }}
 RW_IRAM1 0x20000000 0x8000 {{ .ANY (+RW +ZI) }}
}}
''',encoding='ascii')
    command([arm/'armlink.exe','--cpu=Cortex-M4.fp','--scatter',scatter,'--strict','--map','--symbols','--callgraph',
        '--info=sizes,totals','--list',out/'image.map','--output',out/'locked-foc.axf',*objects])
    command([arm/'fromelf.exe','--i32combined','--output',out/'locked-foc.hex',out/'locked-foc.axf'])
    if any(digest(source/name)!=value for name,value in before.items()): raise RuntimeError('Private source changed during build')
    manifest={'schema_version':1,'mode':'full-foc-can-motion-inhibited-build','source_files_unchanged':True,
        'translation_units':len(sources),'linked':True,'hardware_executed':False,'flash_programming':False,
        'motion_enable_implemented':False,'capabilities':0,'temperature_sensor_implemented':False,
        'production_boot_identity_implemented':False,'controller_preserved':'PI plus existing NNSMC overlay',
        'elf_sha256':digest(out/'locked-foc.axf'),'hex_sha256':digest(out/'locked-foc.hex'),
        'audited_input_sha256':AUDITED,'audited_source_tree_sha256':tree_hash,
        'source_files_checked':len(before),'adapter_sha256':digest(ours/'motor_td3_g431_adapter.c')}
    (out/'build-summary.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True)
    p.add_argument('--arm-bin',required=True);p.add_argument('--output',required=True)
    print(json.dumps(build(p.parse_args()),indent=2))

if __name__=='__main__': main()
