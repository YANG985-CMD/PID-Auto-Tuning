"""Bounded HELLO/STOP-heartbeat test for the audited locked watchdog image.

Prepare only with motor power disconnected. The known image is initialized,
halted with IWDG debug freeze, and given a one-use boot token. Run requires the
operator's board-power confirmation. No BEGIN/GAINS, Flash or option writes.
Keep PCAN ACKs during heartbeat withdrawal and reset-catch inspection.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import struct
import time
import re
import speedloop_watchdog_validate as v
import speedloop_can_capture as capture
import can_transport as wire

REGS=['read32 0x40012C00 4','read32 0x40012C20 4','read32 0x40012C44 4']

def debugger(session,commands,out,name):
    cmd=[session['pyocd'],'commander','--no-config','-t','cortex_m','-u',session['uid'],'-W','-M','attach']
    for c in commands: cmd+=['-c',c]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
    text=p.stdout+p.stderr;(out/name).write_text(text,encoding='utf-8')
    if p.returncode: raise RuntimeError('Debug command failed: '+name)
    return text

def checked_image(session,out):
    m=json.loads(Path(session['manifest']).read_text());image=Path(session['image']).read_bytes();v.validate(m,image)
    file=out/'image-readback-private.bin';second=out/'image-confirmation-private.bin'
    t=debugger(session,['st',*REGS,'read32 0xE0042000 4',
                        f'savemem 0x08000000 {v.IMAGE_BYTES} "{file.as_posix()}"',
                        f'savemem 0x08000000 {v.IMAGE_BYTES} "{second.as_posix()}"'],out,'image-check.txt')
    if (v.common.word(t,0xE0042000)&0xFFF!=0x468
        or file.read_bytes()!=image or second.read_bytes()!=image):
        raise ValueError('Whole image/device preflight failed')
    v.off(t)
    if not re.search(r'Core 0 .*:\s+Halted\b',t): raise ValueError('Preparation core must be halted')
    return m

def status_command(m,file): return f'savemem 0x{m["symbols"][v.NAMES[0]]:x} 56 "{file.as_posix()}"'

def prepare(a):
    if not a.power_stage_disconnected: raise ValueError('Existing physical motor-power disconnection required')
    build=Path(a.build).resolve();out=v.common.fresh(a.output)
    s=dict(schema_version=1,firmware_id=v.IDENTITY,manifest=str(build/'build-summary.json'),
           image=str(build/'speedloop-diagnostic.bin'),pyocd=a.pyocd,uid=a.uid,
           boot=secrets.randbits(64) or 1,prepared=False)
    m=checked_image(s,out);sy=m['symbols']
    t=debugger(s,['read32 0xE0042008 4'],out,'debug-setting.txt');s['old_freeze']=v.common.word(t,0xE0042008)
    file=out/'prepared-status.bin';token=sy['motor_td3_g431_debugger_boot_token']
    try:
        t=debugger(s,['reset halt system','ww 0x40021094 0x00800000','ww 0xE000EDFC 0x01000001',
                     'c','sleep 300','halt',f'ww 0xE0042008 0x{s["old_freeze"]|0x1000:x}',
                     status_command(m,file),*REGS,f'read32 0x{sy["irq_fault"]:x} 4',
                     f'read32 0x{sy["endpoint_ready"]:x} 4',
                     f'ww 0x{token:x} 0x{s["boot"]&0xFFFFFFFF:x}',
                     f'ww 0x{token+4:x} 0x{s["boot"]>>32:x}',
                     f'read32 0x{token:x} 8','read32 0xE0042008 4'],out,'prepare.txt')
        b=v.box(file.read_bytes());v.off(t)
        if (b['active']!=1 or b['fault'] or b['boot_latched'] or b['feeds']<20 or b['link_armed']
            or v.common.word(t,sy['irq_fault']) or v.common.word(t,sy['endpoint_ready'])
            or not v.common.word(t,0xE0042008)&0x1000):
            raise ValueError('Prepared watchdog/identity/output state failed')
        s['prepared']=True;s['status']=b;v.common.save(out/'session-private.json',s)
        return dict(prepared=True,core='Halted',pwm_enabled=False,iwdg_debug_frozen=True,
                    session=str(out/'session-private.json'),firmware_id=v.IDENTITY)
    except Exception:
        debugger(s,['reset halt system',f'ww 0xE0042008 0x{s["old_freeze"]:x}'],out,'prepare-cleanup.txt')
        raise

def datagram(link,obj,nonce,boot=0,seq=0):
    if obj['type'] not in ('hello','stop'): raise ValueError('Only HELLO or STOP permitted')
    frames=wire.fragment(wire.pack(obj,nonce,boot,seq),seq%255 or 1)
    began=time.monotonic()
    for f in frames:
        if time.monotonic()-began>=wire.FRAGMENT_TIMEOUT: raise ValueError('Diagnostic datagram budget exceeded')
        link.send(f);time.sleep(.0005)
    return len(frames)

def received(link):
    link.mode();code,msg,stamp=link.api.Read(link.handle)
    if link.value(code)==link.value(link.basic.PCAN_ERROR_QRCVEMPTY): return None
    link.check(code)
    if link.value(msg.MSGTYPE)!=link.value(link.basic.PCAN_MESSAGE_STANDARD) or link.value(msg.LEN)!=8:
        raise ValueError('Unexpected CAN frame type/DLC')
    return link.value(msg.ID),bytes(msg.DATA[:8]),(link.value(stamp.micros)+1000*link.value(stamp.millis)
        +1000*(1<<32)*link.value(stamp.millis_overflow))

def run(a):
    if not a.allow_live or not a.board_power_confirmed:
        raise ValueError('Requires existing board-power confirmation and diagnostic authorization')
    s=json.loads(Path(a.session).read_text())
    if not s.get('prepared') or s.get('firmware_id')!=v.IDENTITY: raise ValueError('Expected a prepared locked session')
    out=v.common.fresh(a.output)
    r=dict(schema_version=1,mode='speedloop-real-can-stop-heartbeat-withdrawal',verified=False,
           firmware_id=v.IDENTITY,bin_sha256=v.AUDITED_SHA,board_power_confirmed_by_user=True,
           motor_start_requested=False,gains_applied=False,td3_experiences=0,
           physical_cable_disconnected=False,physical_shutoff_latency_validated=False)
    link=None;image_ok=False
    try:
        m=checked_image(s,out);image_ok=True;sy=m['symbols'];file=out/'preflight-status.bin'
        t=debugger(s,[status_command(m,file),'read32 0xE0042008 4',
                     f'read32 0x{sy["endpoint_ready"]:x} 4',f'read32 0x{sy["irq_fault"]:x} 4'],out,'preflight.txt')
        b=v.box(file.read_bytes())
        if (b['active']!=1 or b['fault'] or b['link_armed'] or b['boot_latched']
            or not v.common.word(t,0xE0042008)&0x1000
            or v.common.word(t,sy['endpoint_ready']) or v.common.word(t,sy['irq_fault'])):
            raise ValueError('Prepared session changed; no CAN request sent')
        link=wire.PcanLink(a.channel)
        nonce=secrets.randbits(64) or 1
        with (out/'can-private.jsonl').open('x',encoding='utf-8') as log:
            collector=capture.Collector(nonce,s['boot'],lambda row: log.write(json.dumps(row)+'\n'),identity=v.IDENTITY)
            debugger(s,[f'ww 0xE0042008 0x{s["old_freeze"]&~0x1000:x}','c'],out,'resume.txt')
            tx=datagram(link,dict(type='hello',profile_id=v.IDENTITY),nonce)
            began=time.monotonic();due=began;seq=0
            while time.monotonic()-began<.8:
                now=time.monotonic();collector.check_freshness(now,began)
                if collector.hello and now>=due:
                    seq+=1;tx+=datagram(link,{'type':'stop'},nonce,s['boot'],seq);due=time.monotonic()+.05
                frame=received(link)
                if frame: collector.feed(*frame[:2],time.monotonic(),frame[2])
                else: time.sleep(.001)
            if collector.hello is None or collector.cycles<3 or seq<3:
                raise ValueError('Healthy HELLO/STOP diagnostic window insufficient')
            r.update(collector.summary());r['stop_heartbeats_sent']=seq;r['tx_frames']=tx
            # Keep physical link and ACKs alive, but send no more application heartbeats.
            tail=time.monotonic();fault_status=False
            while time.monotonic()-tail<.65:
                frame=received(link)
                if frame:
                    identifier,data,stamp=frame
                    log.write(json.dumps(dict(phase='heartbeat_withdrawn',id=identifier,data=data.hex(),stamp=stamp))+'\n')
                    if identifier==0x622:
                        fields=capture.decode_diag(identifier,data)
                        if fields['outputs_enabled']: raise ValueError('Outputs enabled during withdrawal')
                        fault_status|=fields['irq_fault']
                else: time.sleep(.001)
            r['fault_status_observed_on_can']=fault_status
        file=out/'reset-status.bin'
        t=debugger(s,['st','reg pc','reg xpsr','read32 0x40021094 4',*REGS,status_command(m,file)],out,'reset-catch.txt')
        v.reset_caught(t,m['entry']);b=v.box(file.read_bytes())
        if b['fault']!=7 or b['link_seq']!=seq or not b['link_armed']:
            raise ValueError('Real CAN heartbeat expiry did not latch the expected link fault')
        r['at_reset']=b;r['real_link_timeout_validated']=True
        file=out/'postboot-status.bin'
        t=debugger(s,['c','sleep 100','halt',status_command(m,file),*REGS],out,'postboot.txt')
        b=v.box(file.read_bytes());v.off(t)
        if b['boot_latched']!=1 or b['active'] or b['feeds'] or not b['reset_flags']&0x20000000:
            raise ValueError('Post-reset boot did not remain motion inhibited')
        r['post_reset_boot']=b;r['verified']=True
    except Exception as exc: r['error']=str(exc)
    finally:
        if image_ok:
            try:
                # No powered manual reset. Freeze halted known diagnostic, then release ACKs.
                event=out/'last-tx-event.bin';held=out/'held-status.bin'
                t=debugger(s,['halt',f'ww 0xE0042008 0x{s["old_freeze"]|0x1000:x}','st',*REGS,
                    status_command(m,held),f'read32 0x{sy["motor_td3_g431_tx_fault"]:x} 4',
                    f'savemem 0x{sy["motor_td3_g431_tx_last_event"]:x} 40 "{event.as_posix()}"'],out,'cleanup.txt')
                r['held_status']=v.box(held.read_bytes())
                r['tx_fault']=v.common.word(t,sy['motor_td3_g431_tx_fault'])
                fields='id id_type frame_type dlc esi brs format timestamp marker event_type'.split()
                r['last_tx_event']=dict(zip(fields,struct.unpack('<10I',event.read_bytes())))
                r['final_pwm_registers']=v.off(t)
                r['core_left_halted']=bool(re.search(r'Core 0 .*:\s+Halted\b',t))
                if not r['core_left_halted']: r['verified']=False
            except Exception as exc: r['cleanup_error']=str(exc);r['verified']=False
        if link is not None:
            try: link.close();r['adapter_released']=True
            except Exception as exc: r['close_error']=str(exc);r['verified']=False
        v.common.save(out/'result.json',r)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    prep=sub.add_parser('prepare')
    for n in ('build','output','pyocd','uid'): prep.add_argument('--'+n,required=True)
    prep.add_argument('--power-stage-disconnected',action='store_true')
    test=sub.add_parser('run')
    for n in ('session','output'): test.add_argument('--'+n,required=True)
    test.add_argument('--channel',default='PCAN_USBBUS1')
    test.add_argument('--allow-live',action='store_true');test.add_argument('--board-power-confirmed',action='store_true')
    a=p.parse_args();r=prepare(a) if a.mode=='prepare' else run(a);print(json.dumps(r,indent=2))
    if a.mode=='run' and not r['verified']: raise SystemExit(1)

if __name__=='__main__': main()
