"""Flash and validate only the audited motion-inhibited SpeedLoop watchdog image.

Requires session-confirmed physical motor power disconnection. Saves private
Flash recovery/readbacks under the task temp directory. No CAN transmissions,
motion, gain application or automatic application recovery. Ends reset/halted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import g431_watchdog_pil as common
import build_speedloop_diagnostic as builder

IDENTITY='g431-speedloop-wdog-v1'
AUDITED_SHA='ea6bb46181092ed415cdcc804ceccac6c14fdedfa8861d3797f1f6fa9c41e54d'
IMAGE_BYTES=35620
FIELDS='magic active fault feeds main_count tick_count adc_count link_armed link_seq last_feed_ms now_ms reset_flags boot_latched irq_fault'.split()
NAMES=('motor_td3_g431_wd_status','motor_td3_g431_wd_test_mode','motor_td3_speedloop_sample_count',
       'motor_td3_speedloop_sample_errors','motor_td3_g431_debugger_boot_token','irq_fault','endpoint_ready','Motor_state')


def validate(manifest,data):
    if (manifest.get('firmware_id')!=IDENTITY or manifest.get('mode')!=builder.MODE
        or manifest.get('watchdog_integrated') is not True or manifest.get('capabilities')!=0
        or manifest.get('diagnostic_fault_injection') is not True
        or manifest.get('motion_enable_implemented') is not False
        or manifest.get('gain_application_implemented') is not False
        or manifest.get('forbidden_motion_symbols_absent') is not True
        or manifest.get('source_tree_sha256')!=builder.SOURCE_TREE_SHA256
        or manifest.get('image_bytes')!=IMAGE_BYTES or len(data)!=IMAGE_BYTES
        or manifest.get('bin_sha256')!=AUDITED_SHA or common.sha(data)!=AUDITED_SHA
        or struct.unpack_from('<II',data)!=(0x20008000,manifest.get('entry'))):
        raise ValueError('Expected the audited motion-inhibited watchdog image')
    names=builder.FILES+builder.WATCHDOG_FILES
    expected={n:builder.digest(builder.SKILL/'firmware'/n) for n in names}
    if manifest.get('integration_sha256')!=expected:
        raise ValueError('Build/source fingerprint differs; rebuild and audit')
    for name in NAMES:
        a=manifest['symbols'][name]
        if not isinstance(a,int) or not 0x20000000<=a<0x20008000-56:
            raise ValueError('Invalid diagnostic symbol address')


def box(data):
    if len(data)!=4*len(FIELDS): raise ValueError('Incomplete watchdog status')
    result=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),data)))
    if result['magic']!=0x53445731: raise ValueError('Unexpected watchdog status identity')
    return result


def off(trace):
    regs={f'0x{a:08X}':common.word(trace,a) for a in (0x40012C00,0x40012C20,0x40012C44)}
    for a,mask in ((0x40012C00,1),(0x40012C20,0xFFFFFFFF),(0x40012C44,0x8000)):
        for match in re.finditer(rf'(?im)^{a:08x}:\s+([0-9a-f]{{8}})\b',trace):
            if int(match[1],16)&mask: raise ValueError('Enabled output in a diagnostic register sample')
    if regs['0x40012C00']&1 or regs['0x40012C20'] or regs['0x40012C44']&0x8000:
        raise ValueError('TIM1 output isolation not proven')
    return regs


def healthy(record,trace):
    off(trace)
    if not (record['active']==1 and record['fault']==0 and record['feeds']>=50
            and record['adc_count']>=50 and record['tick_count']>=500
            and record['boot_latched']==0 and record['link_armed']==0):
        raise ValueError('Healthy ADC/foreground/tick feeding not proven')


def reset_caught(trace,entry):
    off(trace)
    if (not re.search(r'Core 0 .*:\s+Halted\b',trace)
        or common.register(trace,'pc')!=(entry&~1) or common.register(trace,'xpsr')&0x1FF
        or not common.word(trace,0x40021094)&0x20000000):
        raise ValueError('New IWDG reset was not caught at the audited reset vector')


def run(a):
    if not a.power_stage_disconnected or not a.reset_and_halt_ack:
        raise ValueError('Existing physical power-disconnection and reset/Flash authorization required')
    build=Path(a.build).resolve();m=json.loads((build/'build-summary.json').read_text())
    image=(build/'speedloop-diagnostic.bin').read_bytes();validate(m,image)
    out=common.fresh(a.output);symbols=m['symbols']
    r=dict(schema_version=1,mode='speedloop-integrated-watchdog-power-off-validation',verified=False,
           hardware_executed=True,power_disconnected_confirmed_by_user=True,
           flash_programming=True,motor_output=False,foc_executed=False,actor_executed=False,
           gains_applied=False,external_can=False,real_link_timeout_validated=False,
           physical_shutoff_latency_validated=False,firmware_id=IDENTITY,
           image_bytes=IMAGE_BYTES,bin_sha256=AUDITED_SHA,cases=[])
    old_freeze=None;identified=False
    def debug(commands,name,flash=False):
        cmd=[a.pyocd,'commander','--no-config','-u',a.uid,'-W','-M','attach',
             '-t','stm32g431cbux' if flash else 'cortex_m']
        if flash: cmd+=['--pack',a.pack]
        for c in commands: cmd+=['-c',c]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
        text=p.stdout+p.stderr;(out/name).write_text(text,encoding='utf-8')
        if p.returncode: raise RuntimeError('Debug command failed: '+name)
        return text
    read_off=['read32 0x40012C00 4','read32 0x40012C20 4','read32 0x40012C44 4']
    def save_status(path): return f'savemem 0x{symbols[NAMES[0]]:x} 56 "{path.as_posix()}"'
    def start():
        return ['reset halt system','ww 0x40021094 0x00800000',
                'ww 0xE000EDFC 0x01000001','c']
    try:
        t=debug(['st','read32 0xE0042000 4','read32 0x1FFF75E0 4',
                 'read32 0x40022020 4','read32 0xE0042008 4',*read_off],'identity.txt')
        if (common.word(t,0xE0042000)&0xFFF!=0x468 or common.word(t,0x1FFF75E0)&0xFFFF!=128
            or not common.word(t,0x40022020)&0x10000):
            raise ValueError('Unexpected device/Flash/software-IWDG options')
        off(t);identified=True;old_freeze=common.word(t,0xE0042008)
        debug([f'savemem 0x08000000 131072 "{(out/"recovery-flash-private.bin").as_posix()}"'],'backup.txt')
        t=debug(['reset halt system','read32 0xE000E010 4',*read_off],'before-download.txt')
        off(t)
        if common.word(t,0xE000E010)!=0: raise ValueError('SysTick not reset before Flash algorithm')
        debug(['reset halt system',f'load "{(build/"speedloop-diagnostic.hex").as_posix()}"'],
              'download.txt',flash=True)
        debug(['reset halt system',f'savemem 0x08000000 {IMAGE_BYTES} "{(out/"download-readback-private.bin").as_posix()}"'],
              'download-compare.txt')
        if (out/'download-readback-private.bin').read_bytes()!=image: raise ValueError('Full Flash download mismatch')
        r['full_image_download_compare']=True
        status=out/'healthy-status.bin'
        t=debug([*start(),'sleep 600','halt',save_status(status),*read_off,
                 'read32 0xE0042008 4','reset halt system'],'healthy.txt')
        b=box(status.read_bytes());healthy(b,t)
        if common.word(t,0xE0042008)&0x1000: raise ValueError('IWDG debug freeze still enabled')
        r['healthy']=b
        for mode in (1,2,3):
            pre=out/f'case-{mode}-before.bin';caught=out/f'case-{mode}-caught.bin';post=out/f'case-{mode}-postboot.bin'
            t=debug([*start(),'sleep 600',f'ww 0x{symbols[NAMES[1]]:x} {mode}',
                     'sleep 60' if mode==1 else 'sleep 20','halt',save_status(pre),
                     f'read32 0x{symbols["irq_fault"]:x} 4',*read_off,'c','sleep 450',
                     'st','reg pc','reg xpsr','read32 0x40021094 4',*read_off,save_status(caught)],f'case-{mode}.txt')
            before=box(pre.read_bytes());after=box(caught.read_bytes());reset_caught(t,m['entry'])
            if mode==1 and (before['fault']!=6 or after['fault']!=6 or before['feeds']!=after['feeds']):
                raise ValueError('ADC timeout did not latch and cease feeding')
            if mode in (2,3) and (before['feeds']!=after['feeds'] or before['main_count']!=after['main_count']):
                raise ValueError('Failed foreground still progressed or fed')
            irq=common.word(t,symbols['irq_fault'])
            if mode==2 and irq!=1: raise ValueError('SysTick did not detect foreground stall')
            if mode==3 and after['tick_count']!=before['tick_count']: raise ValueError('Masked tick still progressed')
            tpost=debug(['c','sleep 100','halt',save_status(post),*read_off],'postboot-'+str(mode)+'.txt')
            latched=box(post.read_bytes());off(tpost)
            if not (latched['boot_latched']==1 and latched['active']==0 and latched['feeds']==0
                    and latched['reset_flags']&0x20000000):
                raise ValueError('Post-IWDG boot did not remain inhibited before peripheral initialization')
            r['cases'].append(dict(mode=mode,before_reset=before,at_reset=after,
                                 irq_fault_before_reset=irq,post_reset_boot=latched))
        r['verified']=True
    except Exception as exc: r['error']=str(exc)
    finally:
        if identified:
            try:
                cmds=['reset halt system',f'ww 0xE0042008 0x{old_freeze:x}','st',*read_off,
                      'read32 0x40022020 4','read32 0xE0042008 4',
                      f'savemem 0x08000000 {IMAGE_BYTES} "{(out/"final-image-private.bin").as_posix()}"']
                final=debug(cmds,'cleanup.txt');r['final_pwm_registers']=off(final)
                r['core_left_halted']=bool(re.search(r'Core 0 .*:\s+Halted\b',final))
                r['debug_freeze_restored']=common.word(final,0xE0042008)==old_freeze
                r['option_unchanged']=common.word(final,0x40022020)==common.word((out/'identity.txt').read_text(),0x40022020)
                r['final_full_image_compare']=(out/'final-image-private.bin').read_bytes()==image
                if not all(r[k] for k in ('core_left_halted','debug_freeze_restored','option_unchanged','final_full_image_compare')):
                    r['verified']=False
            except Exception as exc: r['cleanup_error']=str(exc);r['verified']=False
        common.save(out/'result.json',r)
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','pyocd','uid','pack'): p.add_argument('--'+name,required=True)
    p.add_argument('--power-stage-disconnected',action='store_true');p.add_argument('--reset-and-halt-ack',action='store_true')
    r=run(p.parse_args());print(json.dumps(r,indent=2))
    if not r['verified']: raise SystemExit(1)


if __name__=='__main__': main()
