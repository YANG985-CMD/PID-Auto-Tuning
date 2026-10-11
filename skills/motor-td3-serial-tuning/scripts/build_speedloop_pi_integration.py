"""Offline PI integration into the audited user's 17.SpeedLoop private copy.

Checks the actual generated PI and compiles the complete Cortex-M4 application.
No Flash/probe/CAN access. USER3 cannot start the resulting review build.
Private vendor files/binaries stay local; publish only own code and summaries.
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
from test_speedloop_pi import run_checks

BUILD_ID='g431-speedloop-pi-review-v1'
FILES=('motor_td3_speedloop_pi.c','motor_td3_speedloop_pi.h',
       'motor_td3_speedloop_pi_bind.c','motor_td3_speedloop_pi_bind.h')
CAN_FILES=('motor_td3_speedloop_can.c','motor_td3_speedloop_can.h',
           'motor_td3_can.c','motor_td3_can.h','motor_td3_can_control.c','motor_td3_can_control.h',
           'motor_td3_guard.c','motor_td3_guard.h','motor_td3_protocol.h',
           'motor_td3_g431_adapter.c','motor_td3_g431_adapter.h','motor_td3_g431_off.h')
CAN_BUILD_ID='g431-speedloop-pi-can-review-v1'
MOTION_BUILD_ID='g431-speedloop-pi-motion-v3'


def patch_copy(copy,can_pi=False,motion=False):
    main=copy/'Core/Src/main.c';text=main.read_text(encoding='utf-8')
    text=replace_once(text,'#include "FOC_Model.h"',
        '#include "FOC_Model.h"\n#include "motor_td3_speedloop_pi_bind.h"\n'
        'const char motor_td3_speedloop_pi_build_id[]="'+(MOTION_BUILD_ID if motion else (CAN_BUILD_ID if can_pi else BUILD_ID))+'";')
    init='\tFuzzyPID_Init(&fuzzy_speed_pid, 0.003389f, 0.00144f, 0.0f, 500.0f, 100.0f);'
    text=replace_once(text,init,'')
    text=replace_once(text,'\tHAL_ADCEx_InjectedStart_IT(&hadc1);',
        '\t/* Initialize every PI owner before the first injected ADC IRQ. */\n'
        '\tFOC_Model_initialize();\n'+init+'\n\tmotor_td3_speedloop_pi_bind_init();\n'
        '\tHAL_ADCEx_InjectedStart_IT(&hadc1);')
    old='\t\t\tFuzzyPID_Compute(&fuzzy_speed_pid, speed_error);\n'+\
        '\t\t\tspd_kpki.spd_kp = fuzzy_speed_pid.Kp;\n\t\t\tspd_kpki.spd_ki = fuzzy_speed_pid.Ki;'
    text=replace_once(text,old,'\t\t\tmotor_td3_speedloop_pi_fast(speed_error);')
    # GCC 14 rejects the vendor's pointer NULL initializers for byte arrays.
    text=replace_once(text,'uint8_t RxData[8]={NULL};','uint8_t RxData[8]={0};')
    text=replace_once(text,'uint8_t TxData[8] = {NULL};','uint8_t TxData[8] = {0};')
    # Review build retains real FOC code and its CH4 sampling setup, but removes
    # all phase-output enable calls. It must not be mistaken for a motion release.
    stop_call=('motor_td3_g431_button_stop();' if motion else
               'motor_td3_speedloop_pi_stop(); /* Review build: stop only. */')
    text=function(text,'HAL_GPIO_EXTI_Callback',
        '  if(GPIO_Pin==Button3_Pin) '+stop_call)
    if motion:
        text=replace_once(text,'\t\tif(ADC_offset == 0)',
            '\t\tmotor_td3_g431_adc_sample();\n\t\tif(ADC_offset == 0)')
        hall_line='\t\tHallTemp = HAL_TIM_ReadCapturedValue(&htim4,TIM_CHANNEL_1);;'
        text=replace_once(text,hall_line,hall_line+'\n'
            '\t\tif(!motor_td3_g431_hall_capture((uint32_t)HallTemp,\n'
            '\t\t  (uint8_t)(((GPIOB->IDR>>8)&1U)|((GPIOB->IDR>>6)&2U)|((GPIOB->IDR>>4)&4U)))) return;')
    text=replace_once(text,'  __disable_irq();','  motor_td3_speedloop_pi_stop();\n  __disable_irq();')
    main.write_text(text,encoding='utf-8',newline='\n')
    if 'HAL_TIMEx_PWMN_Start' in text or 'Motor_OnOff = 1' in text:
        raise ValueError('Unexpected phase enable in PI review copy')
    model=copy/'MATLAB/FOC_Model.c';text=model.read_text(encoding='utf-8')
    text=replace_once(text,'#include "FOC_Model.h"',
        '#include "FOC_Model.h"\n#include "motor_td3_speedloop_pi_bind.h"')
    text=replace_once(text,'    rtb_Sum = spd_kpki.spd_kp * rtb_IntegralGain + Integrator;',
        '''    /* The actual 1ms task owns publication. Preserve the generated
     * previous-input integration, reset priority, saturation and anti-windup. */
    if (!motor_td3_speedloop_pi_model_boundary(rtb_IntegralGain,
        rtDW.Integrator_SYSTEM_ENABLE != 0U ||
        (rtDW.SpeedReset > 0.0 && rtDW.Integrator_PrevResetState <= 0), &Integrator)) {
      return; /* Binding has already disabled physical PWM and start flags. */
    }
    rtb_Sum = spd_kpki.spd_kp * rtb_IntegralGain + Integrator;''')
    model.write_text(text,encoding='utf-8',newline='\n')
    it=copy/'Core/Src/stm32g4xx_it.c';text=it.read_text(encoding='utf-8')
    text=replace_once(text,'#include "FOC_Model.h"',
        '#include "FOC_Model.h"\n#include "motor_td3_speedloop_pi_bind.h"')
    for name in ('NMI_Handler','HardFault_Handler','MemManage_Handler','BusFault_Handler','UsageFault_Handler'):
        text=function(text,name,'  motor_td3_speedloop_pi_stop();\n  while(1) {}')
    text=replace_once(text,'  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */',
        '  /* USER CODE BEGIN TIM1_BRK_TIM15_IRQn 0 */\n  motor_td3_speedloop_pi_stop();')
    it.write_text(text,encoding='utf-8',newline='\n')
    if can_pi:
        text=main.read_text(encoding='utf-8')
        text=replace_once(text,'#include "motor_td3_speedloop_pi_bind.h"',
            '#include "motor_td3_speedloop_pi_bind.h"\n#include "motor_td3_g431_adapter.h"')
        text=function(text,'HAL_UART_RxCpltCallback','  (void)huart; /* CAN owns commands in this copy. */')
        text=replace_once(text,'\tHAL_UART_Receive_IT(&huart3, (uint8_t *)&aRxBuffer, 1);','')
        text=replace_once(text,'\t\t\tHAL_UART_Transmit_DMA(&huart3,(uint8_t *)tempData,6*4);','')
        text=function(text,'FDCAN_Config','  motor_td3_g431_init();')
        if motion:
            begin=text.index('  /* USER CODE BEGIN 2 */')
            finish=text.index('  /* USER CODE END 2 */',begin)
            text=text[:begin]+'''  /* USER CODE BEGIN 2 */
    FOC_Model_initialize();
    FuzzyPID_Init(&fuzzy_speed_pid,0.003389f,0.00144f,0.0f,500.0f,100.0f);
    motor_td3_speedloop_pi_bind_init();
    rtU.SpeedRef=1000.0f;rtU.v_bus=24.0f;
    HAL_OPAMP_Start(&hopamp1);HAL_OPAMP_Start(&hopamp2);HAL_OPAMP_Start(&hopamp3);
    HAL_ADCEx_Calibration_Start(&hadc1,ADC_SINGLE_ENDED);
    HAL_ADCEx_Calibration_Start(&hadc2,ADC_SINGLE_ENDED);
    HAL_DAC_SetValue(&hdac3,DAC_CHANNEL_1,DAC_ALIGN_12B_R,3000);
    HAL_DAC_Start(&hdac3,DAC_CHANNEL_1);HAL_DAC_Start(&hdac1,DAC_CHANNEL_1);
    HAL_COMP_Start(&hcomp1);HAL_TIMEx_HallSensor_Start_IT(&htim4);
    /* Attach the endpoint before any model/ADC interrupt can call it. */
    FDCAN_Config();
    __HAL_ADC_CLEAR_FLAG(&hadc1,ADC_FLAG_JEOC|ADC_FLAG_EOC);
    __HAL_ADC_CLEAR_FLAG(&hadc2,ADC_FLAG_JEOC|ADC_FLAG_EOC);
    TIM1->ARR=7999;TIM1->CCR4=7998;
    HAL_ADCEx_InjectedStart_IT(&hadc1);HAL_ADCEx_InjectedStart(&hadc2);
    /* Six pins are GPIO low; only CH4 supplies the ADC trigger. */
    HAL_TIM_Base_Start(&htim1);HAL_TIM_PWM_Start(&htim1,TIM_CHANNEL_4);
    motor_td3_g431_sampling_ready();
'''+text[finish:]
        start=text.index('\t\tHAL_ADC_Start(&hadc1);',text.index('  while (1)'))
        end=text.index('    /* USER CODE END WHILE */',start)
        text=text[:start]+'''    static uint32_t bus_due;
    motor_td3_g431_poll();
    if((int32_t)(HAL_GetTick()-bus_due)>=0) {
      bus_due=HAL_GetTick()+10U;
      /* Injected conversions may temporarily own an ADC. Only successful
       * regular conversions refresh the bus measurement; motion rejects stale data. */
      if(HAL_ADC_Start(&hadc1)==HAL_OK && HAL_ADC_Start(&hadc2)==HAL_OK &&
         HAL_ADC_PollForConversion(&hadc1,1)==HAL_OK && HAL_ADC_PollForConversion(&hadc2,1)==HAL_OK) {
        adc_vbus=HAL_ADC_GetValue(&hadc2);Vbus=adc_vbus*3.3f/4096*26;
        rtU.v_bus=Vbus>1.0f?Vbus:24.0f;
        motor_td3_g431_bus_sample();
      }
    }
'''+text[end:]
        main.write_text(text,encoding='utf-8',newline='\n')
        text=it.read_text(encoding='utf-8')
        text=replace_once(text,'#include "motor_td3_speedloop_pi_bind.h"',
            '#include "motor_td3_speedloop_pi_bind.h"\n#include "motor_td3_g431_adapter.h"')
        text=replace_once(text,'  HAL_IncTick();','  HAL_IncTick();\n  motor_td3_g431_tick_1ms();')
        text=replace_once(text,'\tHAL_FDCAN_GetRxMessage(&hfdcan1,FDCAN_RX_FIFO0,&RxHeader,RxData);','')
        it.write_text(text,encoding='utf-8',newline='\n')
        fdcan=copy/'Core/Src/fdcan.c';text=fdcan.read_text(encoding='utf-8')
        text=replace_once(text,'hfdcan1.Init.ExtFiltersNbr = 1;','hfdcan1.Init.ExtFiltersNbr = 0;')
        text=replace_once(text,'hfdcan1.Init.AutoRetransmission = DISABLE;',
            'hfdcan1.Init.AutoRetransmission = ENABLE;')
        fdcan.write_text(text,encoding='utf-8',newline='\n')


def patch_can_port(path,motion=False):
    """Reuse the existing HAL/ring/serialized-Tx port. Keep motion locked."""
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'#include "motor_td3_can_control.h"',
        '#include "motor_td3_can_control.h"\n#include "motor_td3_speedloop_can.h"\n#include "motor_td3_speedloop_pi_bind.h"')
    text=replace_once(text,'static motor_td3_can_control endpoint;',
        'static motor_td3_can_control endpoint;\nstatic motor_td3_speedloop_can pi_link;')
    if not motion:
        text=replace_once(text,'#define LOCKED_FIRMWARE "g431-speedloop-diag-v1"',
            '#define LOCKED_FIRMWARE "'+CAN_BUILD_ID+'"')
        text=replace_once(text,'#define LOCKED_PROFILE "g431-speedloop-diag-v1"',
            '#define LOCKED_PROFILE "'+CAN_BUILD_ID+'"')
    text=replace_once(text,'static uint64_t clock_us(void) { uint32_t p=lock(); uint64_t n=now_us; unlock(p); return n; }',
        'static uint64_t clock_us(void) { return motor_td3_speedloop_pi_time_us(); }')
    text=replace_once(text,'    now_us+=1000U;','    now_us=clock_us();')
    text=replace_once(text,'ring_time[ring_write%RX_CAPACITY]=now_us;',
        'ring_time[ring_write%RX_CAPACITY]=clock_us();')
    legacy_tick='motor_td3_can_control_tick(&endpoint,now_us,1); /* Permanently inhibited. */'
    motion_aware_tick='''motor_td3_can_control_tick(&endpoint,now_us,
            irq_fault||motor_td3_g431_break_seen()||!ADC_offset||
            (now_us>adc_seen_us && now_us-adc_seen_us>5000U));'''
    if motion:
        # The motion adapter owns the live estop predicate and control-task
        # tick. Keep the review transform out of this explicit build.
        pass
    elif legacy_tick in text:
        text=replace_once(text,legacy_tick,
            'motor_td3_can_control_tick_ready(&endpoint,now_us,1,0); /* HELLO/STOP only; gains belong to PI boundary. */')
    elif motion_aware_tick in text:
        text=replace_once(text,motion_aware_tick,
            'motor_td3_can_control_tick_ready(&endpoint,now_us,1,0); /* Review image remains motion inhibited. */')
    elif 'motor_td3_can_control_tick(&endpoint,now_us,estop);' in text:
        text=replace_once(text,'motor_td3_can_control_tick(&endpoint,now_us,estop);',
            'motor_td3_can_control_tick_ready(&endpoint,now_us,1,0); /* Review image is inhibited. */')
    elif not motion:
        raise ValueError('SpeedLoop CAN tick anchor missing')
    old='''        const motor_td3_can_hooks h={0,disable_hook,reject_begin,reject_apply,actual_snapshot};
        endpoint_ready=motor_td3_can_control_init_locked(&endpoint,&h,motor_td3_g431_debugger_boot_token,
            LOCKED_FIRMWARE,LOCKED_PROFILE);'''
    new='''        const motor_td3_can_hooks board={0,disable_hook,reject_begin,reject_apply,actual_snapshot};
        motor_td3_can_hooks h;
        if(motor_td3_speedloop_can_attach(&pi_link,&endpoint,&board,&h)) {
          pi_link.estop=1; /* Review image: no motion capabilities or protection bypass. */
          endpoint_ready=motor_td3_can_control_init_locked(&endpoint,&h,motor_td3_g431_debugger_boot_token,
              LOCKED_FIRMWARE,LOCKED_PROFILE);
        } else motor_td3_g431_fault_irq();'''
    text=replace_once(text,old,new)
    # Preserve previously verified serialized Tx event handling without enabling
    # the watchdog module intended for the separate software-ADC diagnostic.
    for following in ('static uint32_t tx_inflight','    if(tx_inflight)',
                      '    tx_marker=', 'static int tx_completed', '    if(!tx_completed'):
        text=replace_once(text,'#ifdef MOTOR_TD3_SPEEDLOOP_WATCHDOG\n'+following,
            '#if defined(MOTOR_TD3_SPEEDLOOP_WATCHDOG) || defined(MOTOR_TD3_SPEEDLOOP_PI_CAN)\n'+following)
    # TxEvent setup uses two blocks: declaration above and the h.TxEvent block.
    text=text.replace('t->error_history=NAN; /* SpeedLoop has no equivalent previous-error field. */',
        't->error_history=pi_link.previous_error; /* Actual previous PI-boundary error; initially unknown. */')
    text=replace_once(text,'    t->temperature_c=NAN; /* No measured thermal signal in this example. */',
        '    t->temperature_c=NAN; /* No measured thermal signal in this example. */\n'
        '    t->elapsed_ms=endpoint.guard.enabled?(float)(clock_us()-endpoint.guard.started_us)/1000.0f:0.0f;')
    text=replace_once(text,'diag_ready=endpoint.owner && !endpoint.hello_pending;unlock(p);',
        '''diag_ready=endpoint.owner && !endpoint.hello_pending;
        if(!len && diag_ready && endpoint.capabilities==TD3_CAN_CAPABILITIES_ALL && n>=diag_due_us) {
          len=motor_td3_can_make_telemetry(&endpoint,tx_packet);
          if(len>0) diag_due_us=n+DIAG_PERIOD_US;
          else motor_td3_g431_fault_irq(); /* Missing data cannot become training telemetry. */
        }
        unlock(p);''')
    text=replace_once(text,'    if(diag_ready && n>=diag_due_us) {',
        '    if(diag_ready && endpoint.capabilities!=TD3_CAN_CAPABILITIES_ALL && n>=diag_due_us) {')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(a):
    source=Path(a.source).resolve();out=Path(a.output).resolve();root=Path(a.temp_root).resolve()
    arm=Path(a.arm_bin).resolve()
    if root not in out.parents or source in out.parents or out in source.parents:
        raise ValueError('Use a separate task directory under temp-root')
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh empty task directory')
    before=validate_source(source)
    if digest(source/'MATLAB/FOC_Model.c')!=MODEL_SHA256: raise ValueError('Generated model changed')
    project=source/'MDK-ARM/STM32G4_GPIO.uvprojx';sources=[]
    for e in ET.parse(project).findall('.//FilePath'):
        p=(project.parent/e.text.replace('\\','/')).resolve()
        if source not in p.parents: raise ValueError('Source reference escapes tree')
        if p.suffix.lower() in ('.c','.s'): sources.append(p.relative_to(source))
    if len(sources)!=42 or sources[0].suffix.lower()!='.s': raise ValueError('Project units changed')
    out.mkdir(parents=True,exist_ok=True)
    core=run_checks(out/'core-tests',a.compiler)
    copy=out/'private-copy';copy.mkdir()
    for folder in ('Core','Drivers','MATLAB','Middlewares/ST/ARM/DSP/Inc'):
        shutil.copytree(source/folder,copy/folder,ignore=shutil.ignore_patterns('*.o','*.d','*.axf','*.hex','*.bak'))
    patch_copy(copy,a.can_pi,a.motion_can)
    own=copy/'codex-pi';own.mkdir();files=FILES+(CAN_FILES if a.can_pi else ())
    for name in files: shutil.copy2(SKILL/'firmware'/name,own/name)
    if a.can_pi: patch_can_port(own/'motor_td3_g431_adapter.c',a.motion_can)
    env=os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    logs=[]
    def run(argv,record_stdout=True):
        r=subprocess.run([str(x) for x in argv],cwd=out,env=env,capture_output=True,text=True)
        logs.append((r.stdout if record_stdout else '')+r.stderr)
        (out/'build.log').write_text('\n'.join(logs),encoding='utf-8')
        if r.returncode: raise RuntimeError('Integration check/build failed; inspect build.log')
        return r.stdout

    # Host checks compile the same patched generated model, not a substitute PI.
    host=out/'model-tests';host.mkdir()
    (host/'main.h').write_text('#ifndef PI_HOST_MAIN_H\n#define PI_HOST_MAIN_H\n#include <stdint.h>\n#endif\n',encoding='ascii')
    for name in ('fuzzy_pid.c','fuzzy_pid.h'):
        shutil.copy2(source/('Core/Src' if name.endswith('.c') else 'Core/Inc')/name,host/name)
    hostflags=['-std=c99','-O2','-pipe','-Wall','-Wextra','-ffp-contract=off','-fno-fast-math',
               '-DMOTOR_TD3_SPEEDLOOP_PI_HOST','-I'+str(host),'-I'+str(copy/'MATLAB'),'-I'+str(own)]
    ownc=[own/name for name in files if name.endswith('.c') and name!='motor_td3_g431_adapter.c']
    suffix='.exe' if os.name=='nt' else ''
    exe=host/('model-tests'+suffix)
    run([a.compiler,*hostflags,*ownc,copy/'MATLAB/FOC_Model.c',host/'fuzzy_pid.c',
         SKILL/'firmware/tests/speedloop_model_test.c','-lm','-o',exe])
    model=json.loads(run([exe]))
    model.update(scope='actual generated SpeedLoop PI with synthetic observations',hardware_accessed=False)
    traces=[]
    for patched in (False,True):
        trace=host/('patched-trace' if patched else 'original-trace')
        flags=hostflags+([] if patched else ['-DSPEEDLOOP_UNPATCHED_TRACE'])
        run([a.compiler,*flags,*(ownc if patched else []),
             (copy if patched else source)/'MATLAB/FOC_Model.c',host/'fuzzy_pid.c',
             SKILL/'firmware/tests/speedloop_model_trace.c','-lm','-o',str(trace)+suffix])
        traces.append(run([str(trace)+suffix],record_stdout=False))
    if traces[0]!=traces[1] or len(traces[0].splitlines())!=2000:
        raise ValueError('Default fuzzy-mode trace differs from the unpatched model')
    model.update(baseline_trace_rows=2000,baseline_trace_identical=True,trace_observation_fields=9)
    (host/'summary.json').write_text(json.dumps(model,indent=2)+'\n',encoding='utf-8')
    # Raw synthetic traces are temporary and are not published.
    (host/'original-trace.txt').write_text(traces[0],encoding='ascii')
    (host/'patched-trace.txt').write_text(traces[1],encoding='ascii')
    connected=None
    if a.can_pi:
        from test_speedloop_can import run_checks as check_can
        library=host/('connected-pi.dll' if os.name=='nt' else 'connected-pi.so')
        run([a.compiler,*hostflags,'-shared','-fPIC',*ownc,copy/'MATLAB/FOC_Model.c',
             host/'fuzzy_pid.c',SKILL/'firmware/tests/speedloop_can_model_host.c','-lm','-o',library])
        connected=check_can(library,host/'can-checks')

    startup=out/'startup.S'
    startup.write_text(startup_from_vectors((source/sources[0]).read_text(encoding='utf-8')).replace(
        'bl motor_td3_g431_disable','bl motor_td3_speedloop_pi_stop'),encoding='ascii')
    linker=out/'review.ld';linker.write_text(LINKER,encoding='ascii')
    sources.extend(Path('codex-pi')/name for name in files if name.endswith('.c'))
    includes=[copy/p for p in ('Core/Inc','Drivers/STM32G4xx_HAL_Driver/Inc',
        'Drivers/STM32G4xx_HAL_Driver/Inc/Legacy','Drivers/CMSIS/Device/ST/STM32G4xx/Include',
        'Drivers/CMSIS/Include','Middlewares/ST/ARM/DSP/Inc','MATLAB','codex-pi')]
    def tool(name): return arm/('arm-none-eabi-'+name+suffix)
    version=run([tool('gcc'),'--version']).splitlines()[0]
    flags=['-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-std=gnu99',
        '-O2','-g','-pipe','-ffunction-sections','-fdata-sections','-ffp-contract=off','-fno-fast-math',
        '-DSTM32G431xx','-DUSE_HAL_DRIVER','-DARM_MATH_CM4','-Wall','-Wextra']
    if a.can_pi:flags+=['-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC','-DMOTOR_TD3_SPEEDLOOP_PI_CAN']
    if a.motion_can:flags+=['-DMOTOR_TD3_SPEEDLOOP_PI_MOTION','-DMOTOR_TD3_CAN_NO_TEMPERATURE']
    objects=[]
    for i,p in enumerate(sources):
        obj=out/(f'{i:02d}_'+p.stem+'.o');objects.append(obj)
        run([tool('gcc'),*flags,*(['-Werror'] if p.parts[0]=='codex-pi' else []),
             *['-I'+str(d) for d in includes],'-c',startup if i==0 else copy/p,'-o',obj])
    elf=out/'speedloop-pi-review.elf'
    run([tool('gcc'),*flags,'-nostartfiles','--specs=nano.specs','--specs=nosys.specs','-T',linker,
        '-Wl,--gc-sections','-Wl,--undefined=motor_td3_speedloop_pi_queue',
        '-Wl,--undefined=motor_td3_speedloop_pi_build_id',
        *(['-Wl,--undefined=motor_td3_speedloop_can_attach'] if a.can_pi else []),
        '-Wl,-Map='+str(out/'image.map'),
        '-o',elf,*objects,'-lm'])
    for fmt,ext in (('ihex','hex'),('binary','bin')):
        run([tool('objcopy'),'-O',fmt,elf,out/('speedloop-pi-review.'+ext)])
    symbols={}
    for line in run([tool('nm'),'--defined-only',elf]).splitlines():
        items=line.split()
        if len(items)==3:
            try: symbols[items[2]]=int(items[0],16)
            except ValueError: pass
    required={'motor_td3_speedloop_pi_queue','motor_td3_speedloop_pi_state','FOC_Model_step',
              'motor_td3_speedloop_pi_model_boundary','motor_td3_speedloop_pi_stop','FuzzyPID_Compute'}
    if a.can_pi:required.update(('motor_td3_speedloop_can_attach','motor_td3_g431_poll',
        'motor_td3_can_make_telemetry','HAL_FDCAN_RxFifo0Callback'))
    if not required.issubset(symbols): raise ValueError('PI integration hooks not linked')
    if not a.motion_can and 'HAL_TIMEx_PWMN_Start' in symbols: raise ValueError('Phase enable survived review link')
    blob=(out/'speedloop-pi-review.bin').read_bytes();sp,entry=struct.unpack('<II',blob[:8])
    if sp!=0x20008000 or not (entry&1 and 0x08000000<=entry<0x08020000) or len(blob)>0x20000:
        raise ValueError('Unexpected Cortex-M4 image layout')
    if inventory(source)!=before: raise ValueError('Original private source tree changed')
    size_fields=run([tool('size'),elf]).strip().splitlines()[-1].split()
    profile=dict(reference='user-selected 17.SpeedLoop known-running source',
        base_period_s=.0001,speed_pi_period_s=.001,kp=.003389,ki=.00144,
        ki_semantics='continuous integral gain; generated model applies 0.001s once',
        phase_current_nominal_a_per_count=.02197265625,dynamic_offset_samples=10,
        iq_reference_clamp=[-3,3],comparator_dac_code=3000,
        comparator_path='COMP1 PB1 positive / DAC3_CH1 negative -> TIM1 Break high/filter2',
        independent_current_calibration=False,measured_trip_current_a=None,
        temperature_sensor_in_example=False,validated_thermal_limits=None,
        fuzzy_gain_envelope=dict(kp=[.003389*.4,.003389*1.6],ki=[.00144*.5,.00144*1.5]),
        fuzzy_envelope_is_verified_td3_safety_domain=False)
    summary=dict(schema_version=1,build_id=(MOTION_BUILD_ID if a.motion_can else (CAN_BUILD_ID if a.can_pi else BUILD_ID)),passed=core['passed'] and model['passed'],
        core_checks=core,actual_model_checks=model,translation_units=len(sources),
        compiler=version,binary_bytes=len(blob),bin_sha256=digest(out/'speedloop-pi-review.bin'),
        hex_sha256=digest(out/'speedloop-pi-review.hex'),model_input_sha256=MODEL_SHA256,
        own_source_sha256={name:digest(own/name) for name in files},
        image_sections_bytes=dict(text=int(size_fields[0]),data=int(size_fields[1]),bss=int(size_fields[2])),
        source_unchanged=True,reference_profile=profile,phase_start_calls_removed=True,
        idle_sampling_requires_moe=bool(a.motion_can),
        idle_phase_pins_gpio_low=bool(a.motion_can),
        hardware_accessed=False,flash_programmed=False,motion_capable=bool(a.motion_can),motion_approved=False,
        transport_gain_commands_connected=bool(connected),board_can_hal_connected=bool(a.can_pi),
        connected_can_model_checks=connected,td3_actor_connected=False,
        remaining=('integrate verified motion enable, independent motion progress/stop protection and approved thermal policy; connect Actor'
                   if a.can_pi else 'connect guarded CAN actions and coherent applied feedback; validate stop/progress protection in the motion implementation'))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('passed','build_id','translation_units','binary_bytes',
        'source_unchanged','flash_programmed','motion_approved')},ensure_ascii=False))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--arm-bin',required=True);p.add_argument('--compiler',default='gcc')
    p.add_argument('--can-pi',action='store_true',help='Check and link existing CAN protocol to the actual PI boundary')
    p.add_argument('--motion-can',action='store_true',help='Build the explicitly bounded CAN motion adapter; never flashes or authorizes a run')
    p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    args=p.parse_args()
    if args.motion_can and not args.can_pi:
        p.error('--motion-can requires --can-pi')
    build(args)
