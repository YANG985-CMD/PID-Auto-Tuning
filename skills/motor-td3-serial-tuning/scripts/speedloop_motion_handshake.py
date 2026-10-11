"""One bounded HELLO/STOP capture for the explicitly prepared motion-v3 image.

Never sends BEGIN or GAINS, writes RAM, resets, or flashes. Requires a powered
CAN transceiver and the operator's power confirmation. Unknown temperature is
retained as null for this sensorless trial; normal training gates are unchanged.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

import can_transport as wire

IDENTITY='g431-speedloop-pi-motion-v3'
PHASE_MASK=0x555
REGS={'tim1_ccer':0x40012c20,'tim1_bdtr':0x40012c44,
      'gpioa_moder':0x48000000,'gpiob_moder':0x48000400,
      'gpioa_odr':0x48000014,'gpiob_odr':0x48000414,'device_id':0xe0042000}
RAM=('endpoint_ready','initialized','irq_fault','adc_samples','motor_td3_g431_debugger_boot_token',
     'Motor_state','ADC_offset')


def debug(a, commands, name):
    cmd=[sys.executable,'-B',a.pyocd,'commander','--no-config','-t','cortex_m',
         '-u',a.uid,'-f','1M','-M','attach']
    for command in commands:cmd+=['-c',command]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
    (a.output/(name+'.txt')).write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError('Debug operation failed: '+name)
    return r.stdout


def reads(symbols):
    commands=['status']+[f'read32 0x{addr:08x} 4' for addr in REGS.values()]
    for name in RAM:
        width=1 if name in ('Motor_state','ADC_offset') else (8 if name.endswith('token') else 4)
        commands.append(f'read{8 if width==1 else 32} 0x{symbols[name]:08x} {width}')
    commands.append(f'read32 0x{symbols["motor_td3_g431_debugger_boot_token"]+4:08x} 4')
    return commands


def state(text,symbols,after_stop=False):
    values={}
    for name,addr in {**REGS,**{n:symbols[n] for n in RAM}}.items():
        width=2 if name in ('Motor_state','ADC_offset') else 8
        m=re.search(rf'(?im)^{addr:08x}:\s+([0-9a-f]{{{width}}})\b',text)
        if not m:raise RuntimeError('Missing state read: '+name)
        values[name]=int(m[1],16)
    token= symbols['motor_td3_g431_debugger_boot_token']+4
    m=re.search(rf'(?im)^{token:08x}:\s+([0-9a-f]{{8}})\b',text)
    if not m or int(m[1],16):raise RuntimeError('Boot token high half not consumed')
    if (not re.search(r'Core 0 .*:\s+Halted\b',text) or values['device_id']&0xfff!=0x468 or
        values['tim1_ccer']&PHASE_MASK or values['Motor_state'] or
        values['gpioa_moder']&0x3f0000!=0x150000 or values['gpiob_moder']&0xfc000000!=0x54000000 or
        values['gpioa_odr']&0x700 or values['gpiob_odr']&0xe000 or
        values['endpoint_ready']!=1 or values['initialized']!=1 or values['irq_fault'] or
        values['ADC_offset']!=1 or values['adc_samples']<100 or
        values['motor_td3_g431_debugger_boot_token'] or
        bool(values['tim1_bdtr']&0x8000)==bool(after_stop)):
        raise RuntimeError('Prepared sampling or disabled-phase state invalid')
    return values


def capture(a):
    root=Path('E:/simulink/_codex_tmp').resolve()
    a.output=Path(a.output).resolve();build=Path(a.build).resolve()
    if root not in a.output.parents:raise ValueError('Use the approved temporary root')
    if not a.power_confirmed:raise ValueError('Operator power confirmation is required')
    a.output.mkdir(parents=True,exist_ok=True)
    summary=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if summary['build_id']!=IDENTITY or not summary['passed'] or not summary['motion_capable']:
        raise ValueError('Unexpected build identity')
    nm=subprocess.run([a.nm,'--defined-only',str(build/'speedloop-pi-review.elf')],capture_output=True,text=True,check=True)
    symbols={line.split()[2]:int(line.split()[0],16) for line in nm.stdout.splitlines() if len(line.split())==3}
    boot=int(Path(a.boot_token_file).read_text(encoding='utf-8').strip(),16)
    nonce=secrets.randbits(64) or 1;rx=wire.Reassembler(allow_missing_temperature=True)
    result={'schema_version':1,'utc':datetime.now(timezone.utc).isoformat(),'firmware_id':IDENTITY,
            'bin_sha256':summary['bin_sha256'],'passed':False,'begin_sent':False,'gains_sent':False,
            'motion_command_sent':False,'thermal_exception':'operator approved this trial; no thermal gate',
            'temperature_c':None,'td3_training_performed':False,'hardware_accessed':True}
    link=None;verified=False;stop_sent=False;telemetry=[];hello=None;last_seq=0;last_us=0
    def send(obj,sequence,transfer):
        for frame in wire.fragment(wire.pack(obj,nonce,0 if obj['type']=='hello' else boot,sequence),transfer):
            link.send(frame);time.sleep(.001)
    try:
        preimage=a.output/'preflight-private.bin'
        text=debug(a,[f'savemem 0x08000000 {summary["binary_bytes"]} {preimage.as_posix()}']+reads(symbols),'preflight')
        if hashlib.sha256(preimage.read_bytes()).hexdigest()!=summary['bin_sha256']:
            raise RuntimeError('Flash mismatch; no request transmitted')
        result['preflight_state']=state(text,symbols);verified=True
        link=wire.PcanLink('PCAN_USBBUS1')
        debug(a,['c'],'resume')
        send({'type':'hello','profile_id':IDENTITY},0,1)
        started=time.monotonic();stop_at=None
        while time.monotonic()-started<3:
            if hello and stop_at is None and time.monotonic()-started>=2:
                send({'type':'stop'},1,2);stop_sent=True;stop_at=time.monotonic()
            frame=link.receive()
            if frame is None:continue
            packet=rx.feed(frame,time.monotonic())
            if packet is None:continue
            obj,meta=wire.unpack(packet,allow_missing_temperature=True)
            if meta['nonce']!=nonce or meta['boot']!=boot:raise RuntimeError('Session/boot mismatch')
            if obj['type']=='hello':
                if hello or obj['firmware_id']!=IDENTITY or obj['profile_id']!=IDENTITY or set(obj['capabilities'])!=set(wire.CAPABILITIES):
                    raise RuntimeError('Unexpected HELLO identity or duplicate reply')
                hello=obj;result['hello']=obj
            elif obj['type']=='telemetry':
                if not hello or obj['seq']!=last_seq+1 or obj['t_us']<=last_us or obj['enabled'] or obj['fault']:
                    result['rejected_telemetry']=obj
                    raise RuntimeError('Telemetry sequence/state/fault failure')
                if obj['temperature_c'] is not None:raise RuntimeError('Unexpected measured temperature')
                last_seq,last_us=obj['seq'],obj['t_us'];telemetry.append(obj)
                if stop_at is not None and time.monotonic()-stop_at>.3:break
            else:raise RuntimeError('Unexpected response type')
        if not hello or not stop_sent or len(telemetry)<5:raise RuntimeError('Incomplete HELLO/STOP/state capture')
        result.update(passed=True,stop_sent=True,telemetry_packets=len(telemetry),
                      nominal_bus_v_range=[min(t['vbus'] for t in telemetry),max(t['vbus'] for t in telemetry)],
                      nominal_current_a_range=[min(t['current'] for t in telemetry),max(t['current'] for t in telemetry)],
                      applied_seq_values=sorted(set(t['applied_seq'] for t in telemetry)),
                      all_snapshots_disabled=True,all_faults_zero=True)
    except Exception as exc:
        result['error']=str(exc)
    finally:
        if verified:
            try:
                if link and hello and not stop_sent:
                    send({'type':'stop'},1,2);stop_sent=True;time.sleep(.05)
                text=debug(a,['halt']+reads(symbols),'final')
                result['final_board_state']=state(text,symbols,after_stop=True)
                result['core_halted_before_can_release']=True
            except Exception as exc:
                result['passed']=False;result['cleanup_error']=str(exc)
        if link:
            try:link.close();result['can_released']=True
            except Exception as exc:result['passed']=False;result['can_release_error']=str(exc)
        result['stop_sent']=stop_sent
        with (a.output/'telemetry.jsonl').open('w',encoding='utf-8') as f:
            for obj in telemetry:f.write(json.dumps(obj,allow_nan=False)+'\n')
        (a.output/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','pyocd','nm','boot-token-file'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841');p.add_argument('--power-confirmed',action='store_true')
    a=p.parse_args();sys.exit(0 if capture(a)['passed'] else 1)
