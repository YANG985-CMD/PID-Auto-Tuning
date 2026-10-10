"""GNU Arm SRAM IWDG test using pyOCD commander; no Flash/option programming.

Only run after physical motor-power disconnection confirmed in the session.
The guest deliberately stops refreshing, then reset vector catch leaves the
core halted before the original application initializes. Final reset/halt
disarms the software-started IWDG and restores the debug freeze setting.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess

SKILL = Path(__file__).resolve().parents[1]
SOURCES = ('stm32_g431_watchdog.c', 'stm32_g431_watchdog.S')
MODE = 'g431-iwdg-reset-sram-diagnostic'
FIELDS = ('magic schema mode stage error feeds irq_ticks irq_at_starve healthy_cycles '
          'starve_cycles spin_cycles reset_flags_cleared dbg_before dbg_during option_before '
          'tim_cr1 tim_ccer tim_bdtr gpioa_phase gpiob_phase iwdg_pr iwdg_rlr iwdg_winr').split()
RAM, MAILBOX, STACK = 0x20000000, 0x20004400, 0x20005000
LINKER = '''ENTRY(watchdog_entry)
MEMORY { RAM(rwx): ORIGIN = 0x20000000, LENGTH = 16K }
SECTIONS { .vectors : { KEEP(*(.vectors)) . = ALIGN(512); } > RAM
 .text : { *(.text*) *(.rodata*) . = ALIGN(4); } > RAM
 .data : { *(.data*) } > RAM
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM }
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def fresh(path):
    out = Path(path).resolve()
    if Path(r'E:\simulink\_codex_tmp').resolve() not in out.parents:
        raise ValueError('Output must be a separate task directory under E:/simulink/_codex_tmp')
    out.mkdir(parents=True, exist_ok=False)
    return out


def hashes():
    return {name: sha((SKILL/'firmware'/name).read_bytes()) for name in SOURCES}


def build(args):
    out = fresh(args.output)
    arm, cmsis = Path(args.arm_bin).resolve(), Path(args.cmsis_root).resolve()
    suffix = '.exe' if os.name == 'nt' else ''
    tool = lambda name: arm/('arm-none-eabi-'+name+suffix)
    device, core = cmsis/'Device/ST/STM32G4xx/Include', cmsis/'Include'
    if not (device/'stm32g431xx.h').is_file() or not (core/'core_cm4.h').is_file():
        raise ValueError('Expected G431 device and Cortex-M4 headers')
    flags = ['-mcpu=cortex-m4','-mthumb','-mfloat-abi=soft','-std=c99','-O2','-g','-pipe',
             '-ffreestanding','-fno-builtin','-ffunction-sections','-fdata-sections',
             '-Wall','-Wextra','-Werror','-DSTM32G431xx','-I'+str(device),'-I'+str(core)]
    env = os.environ.copy();env.update(TEMP=str(out),TMP=str(out),TMPDIR=str(out))
    logs = []
    def call(argv):
        result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=env, cwd=out)
        logs.append(result.stdout+result.stderr)
        (out/'build.log').write_text('\n'.join(logs), encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Watchdog build failed; inspect build.log')
        return result.stdout
    objects = []
    for i, name in enumerate(SOURCES):
        obj = out/f'{i}.o';objects.append(obj)
        call([tool('gcc'),*flags,'-c',SKILL/'firmware'/name,'-o',obj])
    (out/'guest.ld').write_text(LINKER, encoding='ascii')
    elf = out/'watchdog.elf'
    call([tool('gcc'),*flags,'-nostdlib','-T',out/'guest.ld','-Wl,--gc-sections',
          '-Wl,-Map='+str(out/'image.map'),'-o',elf,*objects])
    call([tool('objcopy'),'-O','binary',elf,out/'watchdog.bin'])
    data = (out/'watchdog.bin').read_bytes();stack, entry = struct.unpack_from('<II',data)
    contract = dict(schema_version=1,mode=MODE,entry=entry,stack_top=stack,load_address=RAM,
                    mailbox_address=MAILBOX,image_bytes=len(data),image_sha256=sha(data),
                    source_sha256=hashes(),flash_programming=False,option_programming=False,
                    motor_output=False,external_can=False,software_iwdg_start=True,
                    nominal_lsi_hz=32000,nominal_timeout_ms=200)
    validate(contract,data);save(out/'build-summary.json',contract)
    return contract


def validate(c, data):
    if (c.get('schema_version')!=1 or c.get('mode')!=MODE
            or any(c.get(k) is not False for k in ('flash_programming','option_programming','motor_output','external_can'))
            or c.get('software_iwdg_start') is not True or c.get('load_address')!=RAM
            or c.get('mailbox_address')!=MAILBOX or c.get('stack_top')!=STACK
            or not 512<len(data)<8192 or c.get('image_bytes')!=len(data)
            or c.get('image_sha256')!=sha(data) or c.get('source_sha256')!=hashes()
            or struct.unpack_from('<II',data)!=(STACK,c.get('entry'))
            or not c['entry']&1 or not RAM+512<=(c['entry']&~1)<RAM+len(data)):
        raise ValueError('Invalid SRAM watchdog contract; rebuild audited source')


def word(text, address):
    match = re.search(rf'(?im)^{address:08x}:\s+([0-9a-f]{{8}})\b',text)
    if not match:
        raise ValueError(f'Missing debug register 0x{address:08X}')
    return int(match[1],16)


def register(trace, name):
    match = re.search(rf'(?im)^{name}\s*=\s*0x([0-9a-f]+)\b',trace)
    if not match:
        raise ValueError('Missing core register '+name)
    return int(match[1],16)


def analyze(raw, trace, mode, reset_vector):
    if len(raw)!=4*len(FIELDS):
        raise ValueError('Incomplete watchdog mailbox')
    box = dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw)))
    if (tuple(box[k] for k in ('magic','schema','mode','stage','error','feeds')) != (0x57444731,1,mode,2,0,60)
            or box['reset_flags_cleared']&0x20000000 or box['dbg_during']&0x1000
            or not box['option_before']&0x10000 or box['healthy_cycles']<9600000
            or box['irq_at_starve']<590 or not 100000<box['spin_cycles']<32000000
            or any(box[k] for k in ('tim_cr1','tim_ccer','tim_bdtr'))
            or (box['gpioa_phase'],box['gpiob_phase'])!=(0x3F0000,0xFC000000)
            or (box['iwdg_pr'],box['iwdg_rlr'],box['iwdg_winr'])!=(3,199,4095)
            or not re.search(r'Core 0 .*:\s+Halted\b',trace)
            or not reset_vector&1 or not 0x08000000<=(reset_vector&~1)<0x08020000
            or register(trace,'pc')!=(reset_vector&~1) or register(trace,'xpsr')&0x1FF
            or not word(trace,0x40021094)&0x20000000
            or word(trace,0x40022020)!=box['option_before']
            or any(word(trace,a) for a in (0x40012C00,0x40012C20,0x40012C44))):
        raise ValueError('Hardware IWDG reset, healthy feeding or output isolation not proven')
    extra = box['irq_ticks']-box['irq_at_starve']
    if (mode==1 and extra<10) or (mode==2 and not 0<=extra<=1):
        raise ValueError('Interrupt starvation mode did not match observed SysTick counts')
    box['additional_systick_after_starvation']=extra
    box['approx_starvation_ms_hsi16']=box['spin_cycles']/16000
    box['reset_csr']=word(trace,0x40021094)
    box['caught_reset_pc']=register(trace,'pc')
    box['caught_reset_xpsr']=register(trace,'xpsr')
    return box


def run(args):
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError('Requires existing physical power-disconnection and reset/SRAM acknowledgement')
    src = Path(args.build).resolve()
    c = json.loads((src/'build-summary.json').read_text(encoding='utf-8'))
    data = (src/'watchdog.bin').read_bytes();validate(c,data)
    out = fresh(args.output)
    report = dict(schema_version=1,mode=MODE,verified=False,power_disconnected_confirmed_by_user=True,
                  flash_programming=False,option_programming=False,motor_output=False,
                  full_foc_executed=False,link_watchdog_hardware_validated=False,
                  physical_shutoff_latency_validated=False,original_application_resumed=False)
    def debug(commands, name):
        argv=[args.pyocd,'commander','--no-config','-t','cortex_m','-u',args.uid,'-W','-M','attach']
        for command in commands: argv+=['-c',command]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=15)
        text=result.stdout+result.stderr;(out/name).write_text(text,encoding='utf-8')
        if result.returncode: raise RuntimeError('Watchdog debug command failed: '+name)
        return text
    identified=False;before=None;old_freeze=None
    try:
        probe=debug(['st','read32 0xE0042000 4','read32 0x1FFF75E0 4',
                     'read32 0xE0042008 4','read32 0x40022020 4'],'identity.txt')
        if word(probe,0xE0042000)&0xFFF!=0x468 or word(probe,0x1FFF75E0)&0xFFFF!=128:
            raise ValueError('Expected G431/G441 128KB identity')
        identified=True;old_freeze=word(probe,0xE0042008)
        if not word(probe,0x40022020)&0x10000:
            raise ValueError('Hardware-start IWDG option unsupported; no option changes allowed')
        debug([f'savemem 0x08000000 131072 "{(out/"flash-before-private.bin").as_posix()}"'],'backup.txt')
        before=(out/'flash-before-private.bin').read_bytes()
        reset_vector=struct.unpack_from('<I',before,4)[0]
        if not reset_vector&1 or not 0x08000000<=(reset_vector&~1)<0x08020000:
            raise ValueError('Expected an existing Flash reset vector for reset catch verification')
        boxes=[]
        for mode in (1,2):
            boxfile=out/f'box-{mode}.bin'
            trace=debug(['reset halt system',f'load "{(src/"watchdog.bin").as_posix()}" 0x20000000',
                         f'ww 0x{MAILBOX+8:08x} {mode}',f'wr msp 0x{STACK:x}','wr psp 0x20005000',
                         'wr control 0','wr primask 1','wr basepri 0','wr faultmask 0',
                         'wr xpsr 0x01000000',f'wr pc 0x{c["entry"]:x}','c','sleep 1500','st',
                         'reg pc','reg xpsr','read32 0x40021094 4','read32 0x40022020 4',
                         'read32 0x40012C00 4','read32 0x40012C20 4','read32 0x40012C44 4',
                         f'savemem 0x{MAILBOX:x} {4*len(FIELDS)} "{boxfile.as_posix()}"'],f'case-{mode}.txt')
            box=analyze(boxfile.read_bytes(),trace,mode,reset_vector);boxes.append(box)
            save(out/f'case-{mode}.json',box)
        report.update(verified=True,cases=boxes,image_sha256=c['image_sha256'],image_bytes=c['image_bytes'],
                      source_sha256=c['source_sha256'],independent_iwdg_reset_verified=True)
    except Exception as exc:
        report['error']=str(exc)
    finally:
        if identified:
            try:
                commands=['reset halt system']
                if old_freeze is not None: commands.append(f'ww 0xE0042008 0x{old_freeze:x}')
                commands+=['st','read32 0x40012C00 4','read32 0x40012C20 4','read32 0x40012C44 4',
                           'read32 0xE0042008 4','read32 0x40022020 4',
                           f'savemem 0x08000000 131072 "{(out/"flash-after-private.bin").as_posix()}"']
                final=debug(commands,'cleanup.txt')
                report['core_left_halted']=bool(re.search(r'Core 0 .*:\s+Halted\b',final))
                report['final_pwm_registers']={f'0x{a:x}':word(final,a) for a in (0x40012C00,0x40012C20,0x40012C44)}
                report['debug_freeze_restored']=word(final,0xE0042008)==old_freeze
                report['flash_unchanged']=before is not None and (out/'flash-after-private.bin').read_bytes()==before
                report['option_unchanged']=word(final,0x40022020)==word(probe,0x40022020)
                if (not report['core_left_halted'] or any(report['final_pwm_registers'].values())
                        or not report['debug_freeze_restored'] or not report['flash_unchanged'] or not report['option_unchanged']):
                    report['verified']=False
            except Exception as exc:
                report['cleanup_error']=str(exc);report['verified']=False
        save(out/'result.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    b=sub.add_parser('build')
    for name in ('arm-bin','cmsis-root','output'): b.add_argument('--'+name,required=True)
    r=sub.add_parser('run')
    for name in ('build','output','pyocd','uid'): r.add_argument('--'+name,required=True)
    r.add_argument('--power-stage-disconnected',action='store_true')
    r.add_argument('--reset-and-halt-ack',action='store_true')
    a=p.parse_args();result=build(a) if a.mode=='build' else run(a)
    print(json.dumps(result,indent=2))
    if a.mode=='run' and not result['verified']: raise SystemExit(1)


if __name__=='__main__': main()
