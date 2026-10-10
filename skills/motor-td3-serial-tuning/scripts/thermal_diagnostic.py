"""Fixed-image, motion-inhibited G431 thermal diagnostic only.

Offline validate is the default-independent entry. Flash/prepare/finish require
current physical motor-power disconnection. Run requires current board power
confirmation. Sole CAN worker sends only HELLO/STOP; no gain or start path.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import threading
import time
import build_speedloop_diagnostic as builder
import can_transport as wire
import thermal_can as heat
import speedloop_can_capture as raw
import speedloop_watchdog_can as old_can
import speedloop_watchdog_validate as old

IDENTITY=heat.FIRMWARE
BIN_SHA='69909f289ae5f5bd0f1d4b7fbe888f08f6d2cd3ddc389b363fa99374ca8f9856'
HEX_SHA='1cc3cdd3cb47f9432643bdd1de0c0bdb1fd6874701ec5f78bc9d64dd6f342766'
IMAGE_BYTES=43580
ENTRY=0x080001D9
SYMBOLS={'motor_td3_g431_wd_status':0x20000E9C,'motor_td3_g431_wd_test_mode':0x20000E98,
    'motor_td3_g431_debugger_boot_token':0x20000DE8,'motor_td3_speedloop_thermal_state':0x20000EF0,
    'motor_td3_speedloop_sample_count':0x20000E08,'motor_td3_speedloop_sample_errors':0x20000E04,
    'irq_fault':0x20000B04,'endpoint_ready':0x20000600,'initialized':0x20000B00,'Motor_state':0x2000007A}
LAYOUT={'size':296,'guard_fault':144,'guard_configured':152,'seed_known':156,'has_window':148,
        'calibrated':204,'initialized':272,'fault':276,'period_us':264,'sample_sequence':240}
REGS=['read32 0x40012C00 4','read32 0x40012C20 4','read32 0x40012C44 4']
CAPTURE_SECONDS=3.0
WORKER_LIMIT_SECONDS=8.0


def sha(data): return hashlib.sha256(data).hexdigest()


def check_can_dependencies():
    """Load the package/driver only; never initialize or open a CAN channel."""
    try:
        package=importlib.import_module('can')
        basic=importlib.import_module('can.interfaces.pcan.basic')
        basic.PCANBasic()  # Loads PCANBasic.dll, without Initialize/SetValue.
    except (ImportError,OSError) as exc:
        raise ValueError('CAN dependency unavailable; configure requirements-can.txt in this Python '
                         'environment/PYTHONPATH before preparing or consuming a session: '+str(exc)) from exc
    return dict(python_can_version=package.__version__,driver_library_loaded=True,
                can_channel_opened=False,probe_accessed=False)


def validate(m, binary, hex_data):
    if (m.get('firmware_id')!=IDENTITY or m.get('mode')!=builder.MODE or
        m.get('image_bytes')!=IMAGE_BYTES or len(binary)!=IMAGE_BYTES or sha(binary)!=BIN_SHA or
        m.get('bin_sha256')!=BIN_SHA or sha(hex_data)!=HEX_SHA or m.get('hex_sha256')!=HEX_SHA or
        m.get('initial_sp')!=0x20008000 or m.get('entry')!=ENTRY or
        struct.unpack_from('<II',binary)!=(0x20008000,ENTRY) or m.get('capabilities')!=0 or
        any(m.get(k) is not True for k in ('watchdog_integrated','thermal_audit_integrated',
            'diagnostic_fault_injection','forbidden_motion_symbols_absent','source_files_unchanged')) or
        any(m.get(k) is not False for k in ('motion_enable_implemented','gain_application_implemented',
            'current_gain_calibrated','thermal_protection_verified','thermal_deployment_approved',
            'temperature_sensor_implemented','thermal_can_training_telemetry','foc_sampling_preserved')) or
        m.get('source_tree_sha256')!=builder.SOURCE_TREE_SHA256 or m.get('model_sha256')!=builder.MODEL_SHA256 or
        m.get('thermal_state_layout')!=LAYOUT or not LAYOUT or
        any(type(m.get('symbols',{}).get(n)) is not int or m['symbols'][n]!=a for n,a in SYMBOLS.items())):
        raise ValueError('Expected the exact audited, motion-inhibited thermal image and Arm layout')
    expected={n:sha((builder.SKILL/'firmware'/n).read_bytes())
              for n in builder.FILES+builder.WATCHDOG_FILES+builder.THERMAL_FILES}
    expected['motor_td3_g431_adapter.c']=sha(builder.patch_thermal_adapter(
        (builder.SKILL/'firmware/motor_td3_g431_adapter.c').read_text(encoding='utf-8')).encode('utf-8'))
    if m.get('integration_sha256')!=expected:
        raise ValueError('Firmware source fingerprint changed; rebuild and audit before hardware access')


def load_build(build):
    build=Path(build).resolve()
    m=json.loads((build/'build-summary.json').read_text(encoding='utf-8'))
    binary=(build/'speedloop-diagnostic.bin').read_bytes();hex_data=(build/'speedloop-diagnostic.hex').read_bytes()
    validate(m,binary,hex_data)
    return m,binary,hex_data


def fresh(path):
    out=Path(path).resolve()
    if os.name=='nt' and Path(r'E:\simulink\_codex_tmp').resolve() not in out.parents:
        raise ValueError('Hardware artifacts must stay under the approved task temp root')
    out.mkdir(parents=True,exist_ok=False);return out


def save(path,obj):
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def debug(s,commands,out,name,flash=False,pack=None):
    cmd=[s['pyocd'],'commander','--no-config','-u',s['uid'],'-W','-M','attach',
         '-t','stm32g431cbux' if flash else 'cortex_m']
    if flash: cmd+=['--pack',pack]
    for c in commands: cmd+=['-c',c]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=40 if flash else 20)
    text=result.stdout+result.stderr;(out/name).write_text(text,encoding='utf-8')
    if result.returncode: raise RuntimeError('Debug command failed: '+name)
    return text


def byte(text,address):
    m=re.search(rf'(?im)^{address:08x}:\s+([0-9a-f]{{2}})\b',text)
    if not m: raise ValueError('Missing byte state')
    return int(m[1],16)


def state_commands(out,prefix):
    return ['st',*REGS,f'savemem 0x{SYMBOLS["motor_td3_g431_wd_status"]:x} 56 "{(out/(prefix+"-watchdog-private.bin")).as_posix()}"',
        f'savemem 0x{SYMBOLS["motor_td3_speedloop_thermal_state"]:x} {LAYOUT["size"]} "{(out/(prefix+"-heat-private.bin")).as_posix()}"',
        'read32 0xE0042008 4','read32 0x40022020 4',
        *[f'read32 0x{SYMBOLS[n]:x} 4' for n in ('irq_fault','initialized','endpoint_ready','motor_td3_speedloop_sample_errors')],
        f'read8 0x{SYMBOLS["Motor_state"]:x} 1']


def thermal_state(data):
    if len(data)!=LAYOUT['size']: raise ValueError('Incomplete thermal RAM state')
    result={n:struct.unpack_from('<Q' if n=='sample_sequence' else '<I',data,o)[0]
            for n,o in LAYOUT.items() if n!='size'}
    expected=dict(guard_fault=1,guard_configured=0,seed_known=0,has_window=0,
                  calibrated=0,initialized=1,fault=2,period_us=0,sample_sequence=0)
    if result!=expected: raise ValueError('Missing-calibration rejection was not observed on the board')
    return dict(feed_fault='calibration',thermal_fault='config',current_calibrated=False,
                thermal_limits_verified=False,initial_heat_known=False,valid_windows=0,
                heat_budget_a2s=[None]*3,motion_approved=False)


def read_state(text,out,prefix,endpoint=None,link=None):
    pwm=old.off(text)
    wd=old.box((out/(prefix+'-watchdog-private.bin')).read_bytes())
    thermal=thermal_state((out/(prefix+'-heat-private.bin')).read_bytes())
    if (wd['active']!=1 or wd['fault'] or wd['boot_latched'] or
        old.common.word(text,SYMBOLS['irq_fault']) or old.common.word(text,SYMBOLS['initialized'])!=1 or
        old.common.word(text,SYMBOLS['motor_td3_speedloop_sample_errors']) or byte(text,SYMBOLS['Motor_state']) or
        (endpoint is not None and old.common.word(text,SYMBOLS['endpoint_ready'])!=endpoint) or
        (link is not None and wd['link_armed']!=link)):
        raise ValueError('Unexpected watchdog/ADC/session/output state')
    return dict(watchdog=wd,thermal=thermal,pwm_registers=pwm)


def checked_image(s,out):
    m,binary,_=load_build(s['build'])
    paths=[out/'preflight-image-private.bin',out/'confirm-image-private.bin']
    text=debug(s,['st',*REGS,'read32 0xE0042000 4','read32 0x1FFF75E0 4',
        *[f'savemem 0x08000000 {IMAGE_BYTES} "{p.as_posix()}"' for p in paths]],out,'image-check-private.txt')
    if (old.common.word(text,0xE0042000)&0xFFF!=0x468 or
        old.common.word(text,0x1FFF75E0)&0xFFFF!=128 or
        not re.search(r'Core 0 .*:\s+Halted\b',text) or any(p.read_bytes()!=binary for p in paths)):
        raise ValueError('Exact whole-image/device/halted preflight failed')
    old.off(text);return m


def flash(a):
    if not a.power_stage_disconnected or not a.reset_and_halt_ack:
        raise ValueError('Current physical motor-power disconnection required before Flash/reset')
    m,binary,hex_data=load_build(a.build);out=fresh(a.output)
    s=dict(pyocd=a.pyocd,uid=a.uid,build=str(Path(a.build).resolve()))
    staged=out/'download-image-private.hex';staged.write_bytes(hex_data)
    r=dict(schema_version=1,verified=False,scope='power-off fixed thermal diagnostic Flash and boot check',
           hardware_executed=True,flash_programming=True,firmware_id=IDENTITY,bin_sha256=BIN_SHA,
           motor_start_requested=False,gains_applied=False,thermal_protection_verified=False)
    identified=False;freeze=None;option=None
    try:
        text=debug(s,['st','read32 0xE0042000 4','read32 0x1FFF75E0 4',
                      'read32 0x40022020 4','read32 0xE0042008 4',*REGS],out,'identity-private.txt')
        option=old.common.word(text,0x40022020);freeze=old.common.word(text,0xE0042008)
        if (old.common.word(text,0xE0042000)&0xFFF!=0x468 or
            old.common.word(text,0x1FFF75E0)&0xFFFF!=128 or not option&0x10000):
            raise ValueError('Unexpected target/Flash/software-IWDG options')
        identified=True
        backup=out/'recovery-flash-private.bin'
        text=debug(s,['reset halt system','st','read32 0xE000E010 4',*REGS,
            f'savemem 0x08000000 131072 "{backup.as_posix()}"'],out,'backup-private.txt')
        old.off(text)
        if old.common.word(text,0xE000E010) or len(backup.read_bytes())!=131072:
            raise ValueError('Pre-download reset or full recovery copy failed')
        if sha(staged.read_bytes())!=HEX_SHA: raise ValueError('Staged image changed')
        debug(s,['reset halt system',f'load "{staged.as_posix()}"'],out,'download-private.txt',True,a.pack)
        compare=out/'download-readback-private.bin'
        debug(s,['reset halt system',f'savemem 0x08000000 {IMAGE_BYTES} "{compare.as_posix()}"'],out,'download-compare-private.txt')
        if compare.read_bytes()!=binary: raise ValueError('Full Flash image differs after download')
        r['full_image_download_compare']=True
        text=debug(s,['reset halt system','ww 0x40021094 0x00800000','ww 0xE000EDFC 0x01000001',
            f'ww 0xE0042008 0x{freeze&~0x1000:x}','c','sleep 600','halt','read32 0xE0042008 4',
            f'ww 0xE0042008 0x{freeze|0x1000:x}',*state_commands(out,'boot')],out,'boot-check-private.txt')
        state=read_state(text,out,'boot',0,0);old.healthy(state['watchdog'],text)
        if old.common.word(text,0xE0042008)&0x1000: raise ValueError('Watchdog unexpectedly debug frozen during test')
        r['watchdog_unfrozen_during_execution']=True
        r['board_state']=state;r['verified']=True
    except Exception as exc: r['error']=str(exc)
    finally:
        if identified:
            try:
                final=out/'final-image-private.bin'
                text=debug(s,['reset halt system',f'ww 0xE0042008 0x{freeze:x}','st',*REGS,
                    'read32 0x40022020 4','read32 0xE0042008 4',
                    f'savemem 0x08000000 {IMAGE_BYTES} "{final.as_posix()}"'],out,'cleanup-private.txt')
                r['final_pwm_registers']=old.off(text)
                r['core_left_halted']=bool(re.search(r'Core 0 .*:\s+Halted\b',text))
                r['option_unchanged']=old.common.word(text,0x40022020)==option
                r['debug_freeze_restored']=old.common.word(text,0xE0042008)==freeze
                r['final_full_image_compare']=final.read_bytes()==binary
                r['verified'] &= all(r[k] for k in ('core_left_halted','option_unchanged','debug_freeze_restored','final_full_image_compare'))
            except Exception as exc: r['cleanup_error']=str(exc);r['verified']=False
        save(out/'result.json',r)
    return r


def prepare(a):
    if not a.power_stage_disconnected: raise ValueError('Current physical power disconnection required before prepare/reset')
    check_can_dependencies()
    load_build(a.build);out=fresh(a.output)
    s=dict(schema_version=1,firmware_id=IDENTITY,build=str(Path(a.build).resolve()),pyocd=a.pyocd,
           uid=a.uid,prepared=False,boot=secrets.randbits(64) or 1)
    checked_image(s,out);identified=True
    text=debug(s,['read32 0xE0042008 4','read32 0x40022020 4'],out,'debug-setting-private.txt')
    s['old_freeze']=old.common.word(text,0xE0042008)
    s['option']=old.common.word(text,0x40022020)
    try:
        text=debug(s,['reset halt system','ww 0x40021094 0x00800000','ww 0xE000EDFC 0x01000001',
            f'ww 0xE0042008 0x{s["old_freeze"]&~0x1000:x}',
            'c','sleep 300','halt',f'ww 0xE0042008 0x{s["old_freeze"]|0x1000:x}',
            *state_commands(out,'prepared')],out,'prepare-private.txt')
        state=read_state(text,out,'prepared',0,0)
        if state['watchdog']['feeds']<20 or not old.common.word(text,0xE0042008)&0x1000:
            raise ValueError('Prepared foreground health/debug hold failed')
        token=SYMBOLS['motor_td3_g431_debugger_boot_token']
        text=debug(s,[f'ww 0x{token:x} 0x{s["boot"]&0xFFFFFFFF:x}',f'ww 0x{token+4:x} 0x{s["boot"]>>32:x}',
            f'read32 0x{token:x} 4',f'read32 0x{token+4:x} 4','st',*REGS],out,'token-private.txt')
        if (old.common.word(text,token)|(old.common.word(text,token+4)<<32))!=s['boot']:
            raise ValueError('One-use token write did not match')
        old.off(text)
        if not re.search(r'Core 0 .*:\s+Halted\b',text): raise ValueError('Preparation unexpectedly running')
        s.update(prepared=True,prepared_at=time.time(),board_state=state)
        save(out/'session-private.json',s)
        return dict(prepared=True,firmware_id=IDENTITY,core_left_halted=True,pwm_enabled=False,
                    session=str(out/'session-private.json'),board_state=state)
    except Exception:
        if identified: debug(s,['reset halt system',f'ww 0xE0042008 0x{s["old_freeze"]:x}'],out,'prepare-cleanup-private.txt')
        raise


class Worker:
    """Sole CAN reader/writer. Continue STOP heartbeats until main confirms halt.

    Primary log ends on a complete thermal packet after 3s. Cleanup tail is
    logged separately and never silently appended as complete audit evidence.
    8s hard total ceiling; no retry, BEGIN, GAINS or post-error heartbeat.
    """
    def __init__(self,link,nonce,boot,out,clock=time.monotonic,sleep=time.sleep):
        self.link,self.nonce,self.boot,self.out,self.clock,self.sleep=link,nonce,boot,out,clock,sleep
        self.stop,self.ready,self.holding=threading.Event(),threading.Event(),threading.Event()
        self.decoder=heat.Decoder();self.diag=raw.Collector(nonce,boot,lambda r:None,identity=IDENTITY)
        self.rows=[];self.error=None;self.tx_frames=self.stop_seq=0;self.completed=False;self.elapsed=0

    def send(self,obj,boot=0):
        if obj['type'] not in ('hello','stop'): raise ValueError('Only HELLO/STOP allowed')
        if obj['type']=='stop' and self.stop_seq>160: raise ValueError('Bounded STOP budget exceeded')
        frames=wire.fragment(wire.pack(obj,self.nonce,boot,self.stop_seq if obj['type']=='stop' else 0),
                             self.stop_seq%255 or 1)
        started=self.clock()
        for frame in frames:
            if self.clock()-started>=.05: raise ValueError('Host CAN fragment deadline exceeded')
            self.link.send(frame);self.tx_frames+=1;self.sleep(.0005)

    def run(self):
        began=self.clock();due=began;last_heat=None
        try:
            with (self.out/'can-private.jsonl').open('x',encoding='utf-8') as log, \
                 (self.out/'cleanup-can-private.jsonl').open('x',encoding='utf-8') as tail:
                self.send(dict(type='hello',profile_id=IDENTITY))
                while not self.stop.is_set() and self.clock()-began<WORKER_LIMIT_SECONDS:
                    now=self.clock()
                    if not self.holding.is_set():
                        self.diag.check_freshness(now,began)
                        self.decoder.heat_rx.check_timeout(now)
                        if self.diag.hello and now-(last_heat if last_heat is not None else began)>.35:
                            raise ValueError('Thermal diagnostic stream timeout')
                    if self.diag.hello and now>=due:
                        self.stop_seq+=1;self.send({'type':'stop'},self.boot);due=self.clock()+.05
                    frame=old_can.received(self.link)
                    if frame is None: self.sleep(.001);continue
                    identifier,data,adapter_us=frame;now=self.clock()
                    row=dict(host_monotonic_s=now,adapter_timestamp_us=adapter_us,arbitration_id=identifier,
                        dlc=8,data_hex=data.hex(),extended=False,remote=False,error=False,status_frame=False,fd=False)
                    target=tail if self.completed or self.holding.is_set() else log
                    target.write(json.dumps(row)+'\n')
                    if self.holding.is_set():
                        if identifier==0x622 and raw.decode_diag(identifier,data)['outputs_enabled']:
                            raise ValueError('Output feedback enabled during cleanup')
                        continue
                    if not self.completed: self.rows.append(row)
                    obj=self.decoder.feed(row)
                    if identifier!=heat.CAN_ID: self.diag.feed(identifier,data,now,adapter_us)
                    if obj:
                        if obj['flags']!=heat.LOCKED or obj['feed_fault_code']!=2 or obj['thermal_fault_code']!=1:
                            raise ValueError('Unexpected thermal state in the fixed uncalibrated firmware')
                        last_heat=now
                        if not self.completed and now-began>=CAPTURE_SECONDS:
                            self.completed=True;self.elapsed=now-began;log.flush();self.ready.set()
                if not self.stop.is_set(): raise ValueError('Bounded CAN worker lifetime exceeded')
        except Exception as exc:
            self.error=str(exc);self.ready.set()


def load_session(path,require_fresh=False):
    path=Path(path).resolve()
    if os.name=='nt' and Path(r'E:\simulink\_codex_tmp').resolve() not in path.parents:
        raise ValueError('Session must be a private task artifact')
    s=json.loads(path.read_text(encoding='utf-8'))
    if (s.get('schema_version')!=1 or s.get('firmware_id')!=IDENTITY or s.get('prepared') is not True or
        type(s.get('boot')) is not int or not 0<s['boot']<2**64 or
        type(s.get('old_freeze')) is not int or not 0<=s['old_freeze']<2**32 or
        type(s.get('option')) is not int or not 0<=s['option']<2**32 or
        (require_fresh and not 0<=time.time()-s.get('prepared_at',0)<=1200)):
        raise ValueError('Invalid/stale prepared thermal session')
    load_build(s['build']);return path,s


def run(a):
    if not a.allow_live or not a.board_power_confirmed:
        raise ValueError('Current board-power confirmation and diagnostic authorization required before access')
    check_can_dependencies()
    path,s=load_session(a.session,True)
    # Exclusive one-use claim before probe/CAN access; never remove or rearm it.
    with path.with_name('run-used-private.json').open('x',encoding='utf-8') as marker:
        json.dump(dict(claimed_at=time.time()),marker)
    out=fresh(a.output)
    r=dict(schema_version=1,verified=False,scope='bounded real CAN fixed thermal rejection diagnostic',
        hardware_executed=True,firmware_id=IDENTITY,bin_sha256=BIN_SHA,flash_programming=False,
        motor_start_requested=False,gains_applied=False,td3_experiences=0,thermal_protection_verified=False)
    link=worker=thread=None;image_ok=False
    try:
        checked_image(s,out);image_ok=True
        token=SYMBOLS['motor_td3_g431_debugger_boot_token']
        text=debug(s,[*state_commands(out,'preflight'),f'read32 0x{token:x} 4',
            f'read32 0x{token+4:x} 4'],out,'preflight-private.txt')
        r['preflight_state']=read_state(text,out,'preflight',0,0)
        if (not old.common.word(text,0xE0042008)&0x1000 or
            (old.common.word(text,token)|(old.common.word(text,token+4)<<32))!=s['boot']):
            raise ValueError('Prepared freeze/token changed; no resume or CAN request')
        link=wire.PcanLink(a.channel)  # Supply ACK before verified locked MCU resumes.
        debug(s,[f'ww 0xE0042008 0x{s["old_freeze"]&~0x1000:x}','c'],out,'resume-private.txt')
        worker=Worker(link,secrets.randbits(64) or 1,s['boot'],out)
        thread=threading.Thread(target=worker.run,daemon=True);thread.start()
        worker.ready.wait(CAPTURE_SECONDS+1.5)
        if not worker.completed or worker.error: raise ValueError(worker.error or 'Bounded capture did not finish')
        r['capture_duration_s']=worker.elapsed
    except Exception as exc: r['error']=str(exc)
    finally:
        if image_ok:
            if worker: worker.holding.set()
            try:
                # CAN worker continues STOP/ACK until verified halt. Never reset while powered.
                text=debug(s,['halt',f'ww 0xE0042008 0x{s["old_freeze"]|0x1000:x}',
                    *state_commands(out,'held')],out,'hold-private.txt')
                r['held_state']=read_state(text,out,'held')
                r['core_left_halted']=bool(re.search(r'Core 0 .*:\s+Halted\b',text))
                r['halted_before_adapter_release']=r['core_left_halted']
                if not r['core_left_halted']: raise ValueError('Final halt was not observed')
            except Exception as exc: r['hold_error']=str(exc)
        if worker:
            worker.stop.set()
            if thread: thread.join(2)
            if thread and thread.is_alive(): r['worker_error']='CAN worker did not retire'
            elif worker.error: r['worker_error']=worker.error
            r.update(stop_heartbeats_sent=worker.stop_seq,tx_frames=worker.tx_frames)
            try:
                audit,snapshots=heat.audit(worker.rows)
                r['thermal_can_audit']=audit
                save(out/'thermal-analysis.json',audit)
                r['complete_heat_snapshots']=len(snapshots)
            except Exception as exc: r['audit_error']=str(exc)
        if link:
            try: link.close();r['adapter_released']=True
            except Exception as exc: r['close_error']=str(exc)
        r['verified']=bool(not any(k in r for k in ('error','hold_error','worker_error','close_error','audit_error')) and
            r.get('core_left_halted') and r.get('adapter_released') and r.get('complete_heat_snapshots',0)>=10 and
            r.get('stop_heartbeats_sent',0)>=10 and r.get('thermal_can_audit',{}).get('passed'))
        save(out/'result.json',r)
    return r


def finish(a):
    if not a.power_stage_disconnected: raise ValueError('Current physical power disconnection required before reset cleanup')
    _,s=load_session(a.session);out=fresh(a.output);checked_image(s,out)
    text=debug(s,['reset halt system',f'ww 0xE0042008 0x{s["old_freeze"]:x}',
                 'st',*REGS,'read32 0xE0042008 4','read32 0x40022020 4'],out,'final-reset-private.txt')
    r=dict(schema_version=1,verified=True,scope='power-off session retirement',firmware_id=IDENTITY,
        core_left_halted=bool(re.search(r'Core 0 .*:\s+Halted\b',text)),pwm_registers=old.off(text),
        debug_freeze_restored=old.common.word(text,0xE0042008)==s['old_freeze'],motion_approved=False)
    r['option_unchanged']=old.common.word(text,0x40022020)==s['option']
    r['verified']=r['core_left_halted'] and r['debug_freeze_restored'] and r['option_unchanged']
    save(out/'result.json',r);return r


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    check=sub.add_parser('validate');check.add_argument('--build',required=True)
    sub.add_parser('dependencies')
    for mode in ('flash','prepare'):
        q=sub.add_parser(mode)
        for name in ('build','output','pyocd','uid'): q.add_argument('--'+name,required=True)
        q.add_argument('--power-stage-disconnected',action='store_true')
        if mode=='flash': q.add_argument('--pack',required=True);q.add_argument('--reset-and-halt-ack',action='store_true')
    q=sub.add_parser('run')
    for name in ('session','output'): q.add_argument('--'+name,required=True)
    q.add_argument('--channel',default='PCAN_USBBUS1');q.add_argument('--allow-live',action='store_true')
    q.add_argument('--board-power-confirmed',action='store_true')
    q=sub.add_parser('finish')
    for name in ('session','output'): q.add_argument('--'+name,required=True)
    q.add_argument('--power-stage-disconnected',action='store_true')
    a=p.parse_args()
    if a.mode=='validate':
        load_build(a.build);r=dict(verified=True,scope='offline exact-image/source/Arm ABI check',hardware_accessed=False)
    elif a.mode=='dependencies': r=dict(verified=True,**check_can_dependencies())
    else: r=globals()[a.mode](a)
    print(json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False))
    if r.get('verified',r.get('prepared')) is not True: raise SystemExit(1)


if __name__=='__main__': main()
