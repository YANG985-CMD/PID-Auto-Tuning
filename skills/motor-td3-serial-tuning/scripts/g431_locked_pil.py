"""Build/run the bundled SRAM disable-helper and locked-endpoint test, not full FOC.

Power-disconnection confirmation is required. No CAN adapter, external frames,
GPIO configuration, ADC, phase waveform or Flash programming. Leaves core halted.
"""
import argparse
import json
import secrets
import struct
import subprocess
import time
from pathlib import Path
import can_transport as wire
import stm32_actor_pil as pil
from can_loopback_pil import safe_registers

SKILL=Path(__file__).resolve().parents[1]
MODE='g431-shared-disable-and-locked-endpoint-pil'
FIELDS='magic schema state error cases passed rejected_mask disable_calls systick_count tim1_ccer tim1_bdtr gpio_clock rcc_apb2enr callback_calls'.split()
SOURCES=('stm32_g431_locked_pil.c','stm32_g431_locked_pil.S','motor_td3_g431_off.h',
    'motor_td3_can_control.c','motor_td3_can_control.h','motor_td3_can.c','motor_td3_can.h',
    'motor_td3_guard.c','motor_td3_guard.h','motor_td3_protocol.h')

def build(a):
    from elftools.elf.elffile import ELFFile
    out=pil.fresh_dir(a.output);arm=Path(a.arm_bin).resolve();cmsis=Path(a.cmsis_root).resolve()
    if not (cmsis/'Device/ST/STM32G4xx/Include/stm32g431xx.h').is_file(): raise ValueError('Need G431 CMSIS headers')
    boot=secrets.randbits(64) or 1
    commands=[('hello',dict(type='hello',profile_id='g431-foc-locked-v1'),0),
        ('begin',dict(type='begin',profile_id='g431-foc-locked-v1',speed_ref=1000,lease_ms=100),1),
        ('gains',dict(type='gains',command_seq=1,kp=.004,ki=.002,lease_ms=100),2),('stop',dict(type='stop'),1)]
    header='#include <stdint.h>\n#define LOCKED_TEST_BOOT UINT64_C(%d)\n'%boot
    for name,obj,seq in commands:
        packet=wire.pack(obj,7,0 if name=='hello' else boot,seq,0 if name in ('hello','stop') else 100000)
        header+='static const uint8_t locked_%s[]={%s};\n'%(name,','.join(str(b) for b in packet))
    (out/'locked_pil_vectors.h').write_text(header,encoding='ascii')
    logs=[];objects=[]
    def command(argv):
        r=subprocess.run([str(x) for x in argv],cwd=out,capture_output=True,text=True)
        logs.append(r.stdout+r.stderr);(out/'build.log').write_text('\n'.join(logs),encoding='utf-8')
        if r.returncode: raise RuntimeError('Locked PIL build failed; inspect build.log')
    flags=['--target=arm-arm-none-eabi','-mcpu=cortex-m4','-mfpu=fpv4-sp-d16','-mfloat-abi=hard',
        '-std=c99','-O2','-g','-Wall','-Wextra','-Werror','-ffp-contract=off','-fno-fast-math','-DSTM32G431xx',
        '-I',cmsis/'Device/ST/STM32G4xx/Include','-I',cmsis/'Include','-I',SKILL/'firmware','-I',out]
    for src,name in (('stm32_g431_locked_pil.S','entry'),('stm32_g431_locked_pil.c','guest'),
                     ('motor_td3_can.c','wire'),('motor_td3_can_control.c','control'),('motor_td3_guard.c','guard')):
        obj=out/(name+'.o');objects.append(obj)
        command([arm/'armclang.exe',*flags,'-c',SKILL/'firmware'/src,'-o',obj])
    (out/'image.sct').write_text('LR_RAM 0x20000000 0x4000 { ER_RAM 0x20000000 0x4000 { entry.o (RESET, +First) .ANY (+RO) .ANY (+RW +ZI) } }\n',encoding='ascii')
    elf=out/'locked-pil.axf'
    command([arm/'armlink.exe','--cpu=Cortex-M4.fp','--entry=locked_pil_entry','--scatter',out/'image.sct',
        '--map','--symbols','--list',out/'image.map','--output',elf,*objects])
    image=bytearray(pil.CODE_LIMIT-pil.RAM);high=pil.RAM
    with elf.open('rb') as f:
        e=ELFFile(f);entry=int(e.header['e_entry'])
        for s in e.iter_segments():
            if s['p_type']!='PT_LOAD': continue
            addr,size=int(s['p_vaddr']),int(s['p_memsz'])
            if not pil.RAM<=addr<addr+size<=pil.CODE_LIMIT: raise ValueError('ELF outside reserved SRAM')
            image[addr-pil.RAM:addr-pil.RAM+len(s.data())]=s.data();high=max(high,addr+size)
    data=bytes(image[:high-pil.RAM]);(out/'locked-pil.bin').write_bytes(data)
    contract=dict(schema_version=1,mode=MODE,entry=entry,load_address=pil.RAM,image_bytes=len(data),image_sha256=pil.sha(data),
        mailbox_address=pil.MAILBOX,stack_bottom=pil.STACK_BOTTOM,stack_top=pil.STACK_TOP,
        external_can=False,motor_output=False,flash_programming=False,full_foc_executed=False,expected_cases=11,
        source_sha256={s:pil.sha((SKILL/'firmware'/s).read_bytes()) for s in SOURCES})
    validate(contract,data);pil.save_json(out/'build-summary.json',contract);return contract

def validate(c,data):
    if c.get('schema_version')!=1 or c.get('mode')!=MODE or c.get('expected_cases')!=11 or any(c.get(k) is not False for k in
        ('external_can','motor_output','flash_programming','full_foc_executed')):
        raise ValueError('Wrong locked test contract')
    for k,v in dict(load_address=pil.RAM,mailbox_address=pil.MAILBOX,stack_bottom=pil.STACK_BOTTOM,stack_top=pil.STACK_TOP).items():
        if c.get(k)!=v: raise ValueError('Wrong RAM layout')
    if not 512<len(data)<=pil.CODE_LIMIT-pil.RAM or c.get('image_bytes')!=len(data) or c.get('image_sha256')!=pil.sha(data):
        raise ValueError('Corrupt SRAM image')
    entry=c.get('entry',0)
    if not isinstance(entry,int) or not entry&1 or not pil.RAM+512<=(entry&~1)<pil.RAM+len(data) or struct.unpack_from('<II',data)!=(pil.STACK_TOP,entry):
        raise ValueError('Wrong entry/vector')
    expected=c.get('source_sha256',{})
    if set(expected)!=set(SOURCES) or any(pil.sha((SKILL/'firmware'/name).read_bytes())!=value for name,value in expected.items()):
        raise ValueError('Rebuild after bundled source changes')

def analyze(data):
    b=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),data)))
    if (tuple(b[k] for k in ('magic','schema','state','error','cases','passed','rejected_mask','callback_calls'))
        !=(0x474C4B31,1,2,0,11,11,3,0) or b['systick_count']<55 or b['disable_calls']<55
        or any(b[k] for k in ('tim1_ccer','tim1_bdtr','gpio_clock','rcc_apb2enr'))):
        raise ValueError('Locked PIL checks failed: '+str(b))
    return b

def run(a):
    if not a.power_stage_disconnected or not a.reset_and_halt_ack: raise ValueError('Requires existing physical power disconnection and RAM-test acknowledgement')
    src=Path(a.build).resolve();c=json.loads((src/'build-summary.json').read_text(encoding='utf-8'));data=(src/'locked-pil.bin').read_bytes()
    validate(c,data);out=pil.fresh_dir(a.output)
    from pyocd.core.target import Target
    s=pil.session(out);target=None;before=None;supported=False
    r=dict(schema_version=1,mode=MODE,verified=False,flash_programming=False,motor_output=False,
        external_can=False,full_foc_executed=False,power_disconnected_confirmed_by_user=True,original_application_resumed=False)
    try:
        s.open();target=s.target;r['identity']=pil.identity(target);supported=True
        target.halt();before=bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.get_state()!=Target.State.HALTED or any(safe_registers(target).values()): raise RuntimeError('Initial halt/PWM/GPIO checks failed')
        target.write_memory_block8(pil.RAM,bytes(pil.STACK_TOP-pil.RAM));target.write_memory_block8(pil.RAM,data)
        target.write_memory_block8(pil.STACK_BOTTOM,bytes([0xA5])*(pil.STACK_TOP-pil.STACK_BOTTOM))
        if bytes(target.read_memory_block8(pil.RAM,len(data)))!=data: raise RuntimeError('SRAM readback failed')
        target.selected_core.write_core_registers_raw(['msp','psp','control','primask','basepri','faultmask','xpsr','pc'],
            [pil.STACK_TOP,pil.STACK_TOP,0,1,0,0,0x01000000,c['entry']])
        target.write32(0xE000ED08,pil.RAM);target.resume();end=time.monotonic()+3
        while time.monotonic()<end and target.get_state()==Target.State.RUNNING: time.sleep(.01)
        target.halt();raw=bytes(target.read_memory_block8(pil.MAILBOX,4*len(FIELDS)))
        pil.save_json(out/'mailbox.json',dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw))))
        r['mailbox']=analyze(raw)
        if any(safe_registers(target).values()): raise RuntimeError('Unexpected peripheral/output activation')
        paint=bytes(target.read_memory_block8(pil.STACK_BOTTOM,pil.STACK_TOP-pil.STACK_BOTTOM))
        first=next((i for i,b in enumerate(paint) if b!=0xA5),len(paint))
        r['stack_observed_bytes']=len(paint)-first;r['stack_bottom_fence_intact']=paint[:64]==bytes([0xA5])*64
        if not r['stack_bottom_fence_intact']: raise RuntimeError('Stack fence failed')
        r.update(verified=True,image_bytes=len(data),image_sha256=pil.sha(data),source_sha256=c['source_sha256'])
    except Exception as exc: r['error']=str(exc)
    finally:
        if target is not None and supported:
            try:
                target.reset_and_halt(Target.ResetType.SYSRESETREQ);r['core_left_halted']=target.get_state()==Target.State.HALTED
                r['final_registers']=safe_registers(target)
                r['flash_unchanged']=before is not None and bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))==before
                if not r['core_left_halted'] or any(r['final_registers'].values()) or not r['flash_unchanged']: r['verified']=False
            except Exception as exc: r['verified']=False;r['cleanup_error']=str(exc)
        try: s.close()
        except Exception as exc: r['verified']=False;r['disconnect_error']=str(exc)
        pil.save_json(out/'result.json',r)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    b=sub.add_parser('build');b.add_argument('--arm-bin',required=True);b.add_argument('--cmsis-root',required=True);b.add_argument('--output',required=True)
    x=sub.add_parser('run');x.add_argument('--build',required=True);x.add_argument('--output',required=True)
    x.add_argument('--power-stage-disconnected',action='store_true');x.add_argument('--reset-and-halt-ack',action='store_true')
    a=p.parse_args();r=build(a) if a.mode=='build' else run(a);print(json.dumps(r,indent=2))
    if a.mode=='run' and not r['verified']: raise SystemExit(1)

if __name__=='__main__': main()
