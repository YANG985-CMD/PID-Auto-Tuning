"""Bounded COMP1 -> TIM1 BIF SRAM diagnostic with MOE/phase outputs always off.

Requires existing physical motor-power disconnection. Not a current calibration,
MOE-clear-from-one test, pin waveform test, full FOC execution or latency test.
"""
import argparse
import json
import struct
import time
from pathlib import Path
import stm32_actor_pil as pil
from can_loopback_pil import compile_guest, safe_registers

SKILL=Path(__file__).resolve().parents[1]
MODE='g431-comp1-break-sram-diagnostic'
FIELDS=('magic schema state error cases passed fault_latched unsafe_samples '
    'samples cycles transition_low transition_high recovery_sr recovery_latch '
    'comp_config dac_mode tim_route tim_break_config gpioa_phase_mode gpiob_phase_mode '
    'tim_cr1 tim_ccer tim_bdtr gpio_clocks').split()
ROW_FIELDS='dac comp_csr tim_sr safe'.split()
ROWS_ADDRESS=0x20004500
SOURCES=('stm32_g431_comp_break.c','stm32_g431_comp_break.S','motor_td3_g431_off.h')
FALSE_FLAGS=('external_can','motor_output','flash_programming','moe_enabled','phase_pins_configured','full_foc_executed')

def source_hashes():
    return {name:pil.sha((SKILL/'firmware'/name).read_bytes()) for name in SOURCES}

def build(args):
    out,c,data=compile_guest(args,'g431_comp_break','comp_break_entry',MODE,0,False)
    c.pop('expected_frames')
    c.update(expected_cases=8,rows_address=ROWS_ADDRESS,source_sha256=source_hashes(),
        moe_enabled=False,phase_pins_configured=False,full_foc_executed=False)
    validate(c,data)
    (out/'comp-break.bin').write_bytes(data);pil.save_json(out/'build-summary.json',c)
    return c

def validate(c,data):
    if c.get('schema_version')!=1 or c.get('mode')!=MODE or c.get('expected_cases')!=8 or any(c.get(k) is not False for k in FALSE_FLAGS):
        raise ValueError('Unexpected diagnostic capabilities')
    for key,value in dict(load_address=pil.RAM,mailbox_address=pil.MAILBOX,
            stack_bottom=pil.STACK_BOTTOM,stack_top=pil.STACK_TOP,rows_address=ROWS_ADDRESS).items():
        if c.get(key)!=value: raise ValueError('Wrong reserved SRAM layout')
    entry=c.get('entry',0)
    if (not isinstance(entry,int) or not entry&1 or not 512<len(data)<=pil.CODE_LIMIT-pil.RAM
        or c.get('image_bytes')!=len(data) or c.get('image_sha256')!=pil.sha(data)
        or not pil.RAM+512<=(entry&~1)<pil.RAM+len(data)
        or struct.unpack_from('<II',data)!=(pil.STACK_TOP,entry)):
        raise ValueError('Invalid SRAM image/vector')
    if c.get('source_sha256')!=source_hashes(): raise ValueError('Rebuild after bundled source changes')

def analyze(raw,trace):
    if len(raw)!=len(FIELDS)*4: raise ValueError('Incomplete diagnostic mailbox')
    m=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw)))
    if (tuple(m[k] for k in ('magic','schema','state','error','cases','passed','fault_latched','unsafe_samples','samples'))
            !=(0x43425231,1,2,0,8,8,1,0,17)
        or tuple(m[k] for k in ('comp_config','dac_mode','tim_route','tim_break_config','gpioa_phase_mode','gpiob_phase_mode'))
            !=(0x141,3,2,0x23078,0x3F0000,0xFC000000)
        or m['recovery_sr']!=0 or m['recovery_latch']!=1
        or any(m[k] for k in ('tim_cr1','tim_ccer','tim_bdtr','gpio_clocks'))
        or not 272000<=m['cycles']<1600000 or len(trace)!=17*16):
        raise ValueError('Completion, route or output isolation failed: '+str(m))
    rows=[dict(zip(ROW_FIELDS,struct.unpack_from('<IIII',trace,i*16))) for i in range(17)]
    if any(r['safe']!=1 or not 0<=r['dac']<=4095 for r in rows): raise ValueError('Unsafe or invalid trace')
    if [r['dac'] for r in rows[:4]]!=[4095,3000,0,4095] or rows[-1]['dac']!=4095:
        raise ValueError('Unexpected threshold sequence')
    value=lambda r:bool(r['comp_csr']&0x40000000)
    if (value(rows[0]) or value(rows[1]) or not value(rows[2]) or value(rows[3]) or value(rows[-1])
        or rows[0]['tim_sr']&0x2180 or rows[1]['tim_sr']&0x2180 or not rows[2]['tim_sr']&0x80):
        raise ValueError('Physical comparator/Break transition was not observed')
    lo,hi=0,4095
    for r in rows[4:16]:
        mid=(lo+hi)//2
        if r['dac']!=mid: raise ValueError('Invalid transition search trace')
        if value(r): lo=mid
        else: hi=mid
    if (lo,hi)!=(m['transition_low'],m['transition_high']) or not 0<lo<hi<3000 or hi!=lo+1:
        raise ValueError('Invalid transition bracket')
    return m,rows

def run(args):
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError('Requires physical motor-power disconnection and RAM-test acknowledgement')
    src=Path(args.build).resolve();c=json.loads((src/'build-summary.json').read_text(encoding='utf-8'))
    data=(src/'comp-break.bin').read_bytes();validate(c,data)
    out=pil.fresh_dir(args.output)
    from pyocd.core.target import Target
    session=pil.session(out);target=None;before=None;supported=False
    r=dict(schema_version=1,mode=MODE,verified=False,power_disconnected_confirmed_by_user=True,
        original_application_resumed=False,current_threshold_calibrated=False,moe_clear_from_one_verified=False,
        physical_output_shutoff_verified=False,shutoff_latency_verified=False,**{k:False for k in FALSE_FLAGS})
    try:
        session.open();target=session.target;r['identity']=pil.identity(target);supported=True
        target.halt()
        if target.get_state()!=Target.State.HALTED: raise RuntimeError('Unable to halt supported target')
        before=bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.get_state()!=Target.State.HALTED or any(safe_registers(target).values()):
            raise RuntimeError('Initial halt/PWM/GPIO checks failed')
        target.write_memory_block8(pil.RAM,bytes(pil.STACK_TOP-pil.RAM))
        target.write_memory_block8(pil.RAM,data)
        target.write_memory_block8(pil.STACK_BOTTOM,bytes([0xA5])*(pil.STACK_TOP-pil.STACK_BOTTOM))
        if bytes(target.read_memory_block8(pil.RAM,len(data)))!=data: raise RuntimeError('SRAM readback mismatch')
        target.selected_core.write_core_registers_raw(
            ['msp','psp','control','primask','basepri','faultmask','xpsr','pc'],
            [pil.STACK_TOP,pil.STACK_TOP,0,1,0,0,0x01000000,c['entry']])
        target.write32(0xE000ED08,pil.RAM);target.resume();deadline=time.monotonic()+3
        while time.monotonic()<deadline and target.get_state()==Target.State.RUNNING: time.sleep(.01)
        target.halt();raw=bytes(target.read_memory_block8(pil.MAILBOX,4*len(FIELDS)))
        m=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw)))
        pil.save_json(out/'mailbox.json',m)
        r['mailbox']=m
        count=m['samples']
        if not 0<count<=24: raise RuntimeError('Guest stopped before a valid trace: state=%d error=0x%X samples=%d'%(m['state'],m['error'],count))
        trace=bytes(target.read_memory_block8(ROWS_ADDRESS,16*count))
        rows=[dict(zip(ROW_FIELDS,struct.unpack_from('<IIII',trace,i*16))) for i in range(count)]
        pil.save_json(out/'trace.json',rows)
        r['mailbox'],r['trace']=analyze(raw,trace)
        if any(safe_registers(target).values()): raise RuntimeError('Guest peripheral shutdown failed')
        paint=bytes(target.read_memory_block8(pil.STACK_BOTTOM,pil.STACK_TOP-pil.STACK_BOTTOM))
        first=next((i for i,b in enumerate(paint) if b!=0xA5),len(paint))
        r['stack_observed_bytes']=len(paint)-first;r['stack_bottom_fence_intact']=paint[:64]==bytes([0xA5])*64
        if not r['stack_bottom_fence_intact']: raise RuntimeError('Stack fence failed')
        r.update(verified=True,image_bytes=len(data),image_sha256=pil.sha(data),source_sha256=c['source_sha256'])
    except Exception as exc: r['error']=str(exc)
    finally:
        if target is not None and supported:
            try:
                target.reset_and_halt(Target.ResetType.SYSRESETREQ)
                r['core_left_halted']=target.get_state()==Target.State.HALTED
                r['final_registers']=safe_registers(target)
                r['flash_unchanged']=before is not None and bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))==before
                if not r['core_left_halted'] or any(r['final_registers'].values()) or not r['flash_unchanged']: r['verified']=False
            except Exception as exc: r['verified']=False;r['cleanup_error']=str(exc)
        try: session.close()
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
