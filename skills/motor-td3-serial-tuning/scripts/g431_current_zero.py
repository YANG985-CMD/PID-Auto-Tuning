"""Observe static ADC offsets in SRAM, or calculate a non-applied nominal plan.

Only for the audited G431/H17 board with motor power physically disconnected.
No PWM, Flash writes, CAN, serial, live gains or protection-threshold updates.
"""
import argparse
import json
import math
import statistics
import struct
import time
from pathlib import Path
import stm32_actor_pil as pil
from can_loopback_pil import compile_guest, safe_registers

SKILL=Path(__file__).resolve().parents[1]
MODE='g431-current-zero-sram-observation'
FIELDS=('magic schema state error cases passed samples unsafe_samples cycles '
    'adc1_calfact adc2_calfact adc_common adc1_smpr1 adc1_smpr2 adc2_smpr1 '
    'adc1_cfgr adc2_cfgr opamp1_csr opamp2_csr opamp3_csr '
    'gpioa_phase_mode gpiob_phase_mode tim_cr1 tim_ccer tim_bdtr gpio_clocks '
    'last_adc1_isr last_adc2_isr').split()
ROW_FIELDS='a b c safe'.split()
ROWS_ADDRESS=0x20004500
SOURCES=('stm32_g431_current_zero.c','stm32_g431_current_zero.S')
FALSE_FLAGS=('external_can','motor_output','flash_programming','moe_enabled',
    'phase_pins_configured','full_foc_executed','protection_threshold_changed')
NOMINAL_A_PER_COUNT=0.02197265625
OPAMP_CONFIG_MASK=0xA007FFFF

def source_hashes():
    return {name:pil.sha((SKILL/'firmware'/name).read_bytes()) for name in SOURCES}

def build(args):
    out,c,data=compile_guest(args,'g431_current_zero','current_zero_entry',MODE,0,False)
    c.pop('expected_frames')
    c.update(expected_cases=7,expected_samples=64,rows_address=ROWS_ADDRESS,
        source_sha256=source_hashes(),moe_enabled=False,phase_pins_configured=False,
        full_foc_executed=False,protection_threshold_changed=False)
    validate(c,data)
    (out/'current-zero.bin').write_bytes(data);pil.save_json(out/'build-summary.json',c)
    return c

def validate(c,data):
    if (c.get('schema_version')!=1 or c.get('mode')!=MODE or c.get('expected_cases')!=7
        or c.get('expected_samples')!=64 or any(c.get(k) is not False for k in FALSE_FLAGS)):
        raise ValueError('Unexpected diagnostic capabilities/counts')
    for k,v in dict(load_address=pil.RAM,mailbox_address=pil.MAILBOX,
            stack_bottom=pil.STACK_BOTTOM,stack_top=pil.STACK_TOP,rows_address=ROWS_ADDRESS).items():
        if c.get(k)!=v:raise ValueError('Wrong reserved SRAM layout')
    entry=c.get('entry',0)
    if (not isinstance(entry,int) or not entry&1 or not 512<len(data)<=pil.CODE_LIMIT-pil.RAM
        or c.get('image_bytes')!=len(data) or c.get('image_sha256')!=pil.sha(data)
        or not pil.RAM+512<=(entry&~1)<pil.RAM+len(data)
        or struct.unpack_from('<II',data)!=(pil.STACK_TOP,entry)):
        raise ValueError('Invalid SRAM image/vector')
    if c.get('source_sha256')!=source_hashes():raise ValueError('Rebuild after bundled source changes')

def analyze(raw,trace):
    if len(raw)!=4*len(FIELDS):raise ValueError('Incomplete mailbox')
    m=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw)))
    if (tuple(m[k] for k in ('magic','schema','state','error','cases','passed','samples','unsafe_samples'))
            !=(0x435A5231,1,2,0,7,7,64,0)
        or tuple(m[k] for k in ('adc_common','adc1_smpr1','adc1_smpr2','adc2_smpr1',
            'adc1_cfgr','adc2_cfgr',
            'gpioa_phase_mode','gpiob_phase_mode'))
            !=(0x30000,0xC00,0x180,0xC00,0,0,0x3F0000,0xFC000000)
        or any(m[k]&OPAMP_CONFIG_MASK!=1 for k in ('opamp1_csr','opamp2_csr','opamp3_csr'))
        or m['adc1_calfact']>127 or m['adc2_calfact']>127
        or m['last_adc1_isr']&0x10 or m['last_adc2_isr']&0x10
        or any(m[k] for k in ('tim_cr1','tim_ccer','tim_bdtr','gpio_clocks'))
        or not 400000<=m['cycles']<16000000 or len(trace)!=64*16):
        raise ValueError('Acquisition completion, configuration or isolation failed: '+str(m))
    rows=[dict(zip(ROW_FIELDS,struct.unpack_from('<IIII',trace,i*16))) for i in range(64)]
    if any(r['safe']!=1 or any(not 0<=r[k]<=4095 for k in ('a','b','c')) for r in rows):
        raise ValueError('Unsafe or invalid ADC trace')
    return m,rows

def zero_statistics(rows):
    result={}
    for phase in ('a','b','c'):
        values=[r[phase] for r in rows]
        mean=statistics.fmean(values)
        result[phase]=dict(samples=len(values),mean_adc=mean,min_adc=min(values),max_adc=max(values),
            span_counts=max(values)-min(values),stddev_counts=statistics.pstdev(values),
            rail_samples=sum(v in (0,4095) for v in values),
            nominal_offset_if_using_2048_a=(mean-2048)*NOMINAL_A_PER_COUNT)
    return result

def nominal_plan(zero,comp):
    """Pure calculation, with no device API and no release of live capabilities."""
    import g431_comp_break as comp_diag
    if (zero.get('mode')!=MODE or zero.get('verified') is not True
        or zero.get('flash_unchanged') is not True or zero.get('core_left_halted') is not True
        or any(zero.get(k) is not False for k in FALSE_FLAGS)
        or comp.get('mode')!='g431-comp1-break-sram-diagnostic' or comp.get('verified') is not True
        or comp.get('current_threshold_calibrated') is not False
        or comp.get('flash_unchanged') is not True or comp.get('core_left_halted') is not True
        or any(comp.get(k) is not False for k in comp_diag.FALSE_FLAGS)):
        raise ValueError('Use completed, nonenergized diagnostic reports')
    m,rows=analyze(struct.pack('<'+'I'*len(FIELDS),*(zero['mailbox'][k] for k in FIELDS)),
        b''.join(struct.pack('<IIII',*(r[k] for k in ROW_FIELDS)) for r in zero['trace']))
    del m
    comp_diag.analyze(struct.pack('<'+'I'*len(comp_diag.FIELDS),*(comp['mailbox'][k] for k in comp_diag.FIELDS)),
        b''.join(struct.pack('<IIII',*(r[k] for k in comp_diag.ROW_FIELDS)) for r in comp['trace']))
    stats=zero_statistics(rows)
    if any(v['rail_samples'] for v in stats.values()):raise ValueError('ADC rails prevent a nominal offset plan')
    lo=comp['mailbox']['transition_low'];hi=comp['mailbox']['transition_high']
    if not isinstance(lo,int) or not isinstance(hi,int) or not 0<lo<hi<3000 or hi!=lo+1:
        raise ValueError('Invalid comparator crossing bracket')
    center=(lo+hi)/2
    # Equal nominal ADC/DAC reference and ideal transfers only. ADC and DAC
    # errors, comparator offset, shunt/gain tolerance and temperature uncalibrated.
    step=3/NOMINAL_A_PER_COUNT
    return dict(schema_version=1,mode='non-applied-nominal-current-threshold-plan',
        current_gain_calibrated=False,current_threshold_calibrated=False,
        hardware_shutoff_verified=False,motor_control_approved=False,device_write=False,
        nominal_a_per_count=NOMINAL_A_PER_COUNT,zero_statistics=stats,
        c_adc_mean_minus_previous_dac_crossing_counts=stats['c']['mean_adc']-center,
        previous_comp_crossing_dac=[lo,hi],
        existing_dac3000_nominal_positive_current_a=[(3000-hi)*NOMINAL_A_PER_COUNT,(3000-lo)*NOMINAL_A_PER_COUNT],
        illustrative_positive_3a=dict(purpose='Arithmetic example only; 3A is not an approved protection trip current',
            ideal_dac_interval=[lo+step,hi+step],nearest_ideal_code=math.floor(center+step+.5)),
        limitations=['Crossing and ADC observations were separate sessions, not a matched calibration',
            'Zero current cannot identify A/count gain; known positive/negative current is still required',
            'Only C-phase upper comparison exists in audited firmware; it is not six-direction protection',
            'No DAC/current-limit/gain value is written by this calculation'])

def run(args):
    if not args.power_stage_disconnected or not args.reset_and_halt_ack:
        raise ValueError('Requires physical motor-power disconnection and RAM-test acknowledgement')
    src=Path(args.build).resolve();c=json.loads((src/'build-summary.json').read_text(encoding='utf-8'))
    data=(src/'current-zero.bin').read_bytes();validate(c,data)
    out=pil.fresh_dir(args.output)
    from pyocd.core.target import Target
    session=pil.session(out);target=None;before=None;supported=False
    r=dict(schema_version=1,mode=MODE,verified=False,power_disconnected_confirmed_by_user=True,
        original_application_resumed=False,current_gain_calibrated=False,current_threshold_calibrated=False,
        physical_output_shutoff_verified=False,production_adc_timing_verified=False,motor_control_approved=False,
        **{k:False for k in FALSE_FLAGS})
    try:
        session.open();target=session.target;r['identity']=pil.identity(target);supported=True
        target.halt()
        if target.get_state()!=Target.State.HALTED:raise RuntimeError('Unable to halt supported target')
        before=bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.get_state()!=Target.State.HALTED or any(safe_registers(target).values()):
            raise RuntimeError('Initial halt/PWM/GPIO checks failed')
        target.write_memory_block8(pil.RAM,bytes(pil.STACK_TOP-pil.RAM))
        target.write_memory_block8(pil.RAM,data)
        target.write_memory_block8(pil.STACK_BOTTOM,bytes([0xA5])*(pil.STACK_TOP-pil.STACK_BOTTOM))
        if bytes(target.read_memory_block8(pil.RAM,len(data)))!=data:raise RuntimeError('SRAM readback mismatch')
        target.selected_core.write_core_registers_raw(
            ['msp','psp','control','primask','basepri','faultmask','xpsr','pc'],
            [pil.STACK_TOP,pil.STACK_TOP,0,1,0,0,0x01000000,c['entry']])
        target.write32(0xE000ED08,pil.RAM);target.resume();deadline=time.monotonic()+3
        while time.monotonic()<deadline and target.get_state()==Target.State.RUNNING:time.sleep(.01)
        target.halt();raw=bytes(target.read_memory_block8(pil.MAILBOX,4*len(FIELDS)))
        m=dict(zip(FIELDS,struct.unpack('<'+'I'*len(FIELDS),raw)))
        pil.save_json(out/'mailbox.json',m);r['mailbox']=m
        count=m['samples']
        if not 0<count<=64:raise RuntimeError('Guest stopped: state=%d error=0x%X samples=%d'%(m['state'],m['error'],count))
        trace=bytes(target.read_memory_block8(ROWS_ADDRESS,16*count))
        rows=[dict(zip(ROW_FIELDS,struct.unpack_from('<IIII',trace,i*16))) for i in range(count)]
        pil.save_json(out/'trace.json',rows)
        r['mailbox'],r['trace']=analyze(raw,trace);r['zero_statistics']=zero_statistics(rows)
        if any(safe_registers(target).values()):raise RuntimeError('Guest peripheral shutdown failed')
        paint=bytes(target.read_memory_block8(pil.STACK_BOTTOM,pil.STACK_TOP-pil.STACK_BOTTOM))
        first=next((i for i,b in enumerate(paint) if b!=0xA5),len(paint))
        r['stack_observed_bytes']=len(paint)-first;r['stack_bottom_fence_intact']=paint[:64]==bytes([0xA5])*64
        if not r['stack_bottom_fence_intact']:raise RuntimeError('Stack fence failed')
        r.update(verified=True,image_bytes=len(data),image_sha256=pil.sha(data),source_sha256=c['source_sha256'])
    except Exception as exc:r['error']=str(exc)
    finally:
        if target is not None and supported:
            try:
                target.reset_and_halt(Target.ResetType.SYSRESETREQ)
                r['core_left_halted']=target.get_state()==Target.State.HALTED
                r['final_registers']=safe_registers(target)
                r['flash_unchanged']=before is not None and bytes(target.read_memory_block8(pil.FLASH,pil.FLASH_BYTES))==before
                if not r['core_left_halted'] or any(r['final_registers'].values()) or not r['flash_unchanged']:r['verified']=False
            except Exception as exc:r['verified']=False;r['cleanup_error']=str(exc)
        try:session.close()
        except Exception as exc:r['verified']=False;r['disconnect_error']=str(exc)
        pil.save_json(out/'result.json',r)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    b=sub.add_parser('build');b.add_argument('--arm-bin',required=True);b.add_argument('--cmsis-root',required=True);b.add_argument('--output',required=True)
    x=sub.add_parser('run');x.add_argument('--build',required=True);x.add_argument('--output',required=True)
    x.add_argument('--power-stage-disconnected',action='store_true');x.add_argument('--reset-and-halt-ack',action='store_true')
    n=sub.add_parser('plan');n.add_argument('--zero-result',required=True);n.add_argument('--comp-result',required=True);n.add_argument('--output',required=True)
    a=p.parse_args()
    if a.mode=='build':r=build(a)
    elif a.mode=='run':r=run(a)
    else:
        r=nominal_plan(json.loads(Path(a.zero_result).read_text(encoding='utf-8')),
            json.loads(Path(a.comp_result).read_text(encoding='utf-8')))
        pil.save_json(pil.fresh_dir(a.output)/'plan.json',r)
    print(json.dumps(r,indent=2))
    if a.mode=='run' and not r['verified']:raise SystemExit(1)

if __name__=='__main__':main()
