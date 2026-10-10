"""Exercise the real bounded-run C module with HAL/register substitutes.
Private source is required for target HAL/CMSIS and generated model type declarations.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path
from build_g431_locked_foc import SKILL


def main(a):
    copy=Path(a.private_copy).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
    if os.name=='nt' and Path('E:/simulink/_codex_tmp').resolve() not in out.parents: raise ValueError('Temp root required')
    mapping={'TIM1':('TIM_TypeDef','fake_tim'),'RCC':('RCC_TypeDef','fake_rcc'),
        'GPIOA':('GPIO_TypeDef','fake_a'),'GPIOB':('GPIO_TypeDef','fake_b'),
        'ADC1':('ADC_TypeDef','fake_adc1'),'ADC2':('ADC_TypeDef','fake_adc2'),
        'DWT':('DWT_Type','fake_dwt'),'CoreDebug':('CoreDebug_Type','fake_debug'),
        'DBGMCU':('DBGMCU_TypeDef','fake_dbgmcu'),'IWDG':('IWDG_TypeDef','fake_iwdg'),
        'FLASH':('FLASH_TypeDef','fake_flash')}
    t='#ifndef BASELINE_HOST_MAIN\n#define BASELINE_HOST_MAIN\n#include "stm32g4xx_hal.h"\n'
    for macro,(kind,name) in mapping.items(): t+=f'extern {kind} {name};\n#undef {macro}\n#define {macro} (&{name})\n'
    t+='''#define __get_PRIMASK() 0U
#define __disable_irq() ((void)0)
#define __set_PRIMASK(p) ((void)(p))
#define __DSB() ((void)0)
#endif
'''
    (out/'main.h').write_text(t,encoding='ascii')
    inc=[out,copy/'Core/Inc',copy/'Drivers/STM32G4xx_HAL_Driver/Inc',copy/'Drivers/STM32G4xx_HAL_Driver/Inc/Legacy',
        copy/'Drivers/CMSIS/Include',copy/'Drivers/CMSIS/Device/ST/STM32G4xx/Include',copy/'MATLAB',SKILL/'firmware']
    exe=out/('checks.exe' if os.name=='nt' else 'checks');env=os.environ.copy();env.update(TMP=str(out),TEMP=str(out),TMPDIR=str(out))
    commands=[[a.compiler,'-std=c99','-O2','-pipe','-DSTM32G431xx','-DUSE_HAL_DRIVER',*['-I'+str(p) for p in inc],
        str(SKILL/'firmware/motor_td3_speedloop_baseline.c'),str(SKILL/'firmware/tests/speedloop_baseline_host.c'),'-lm','-o',str(exe)]]
    commands += [[str(exe),str(i)] for i in range(8)];logs=[]
    for cmd in commands:
        r=subprocess.run(cmd,cwd=out,env=env,capture_output=True,text=True);logs.append(r.stdout+r.stderr)
        (out/'test.log').write_text('\n'.join(logs),encoding='utf-8')
        if r.returncode: raise RuntimeError('Baseline module check failed: inspect test.log')
    summary=dict(passed=True,checks=8,scope='actual bounded-run C; substitute HAL and registers',hardware_accessed=False,
        cases=['deadline and restart latch','missing host cannot start','unpowered bus cannot start','Break disables gates',
               'stale ADC stops','expired heartbeat cannot revive','invalid Hall stops','stalled foreground stops'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-copy',required=True);p.add_argument('--output',required=True)
    p.add_argument('--compiler',default='gcc');main(p.parse_args())
