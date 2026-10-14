"""Single fixed-PI 5s startup trace. Exact v9 image, no Actor, no retry."""
import argparse,hashlib,json,struct,subprocess
from pathlib import Path
from build_speedloop_startup_review import IDENTITY
from speedloop_duration_review import overrides
import speedloop_motion_gain_trial as trial
from speedloop_motion_handshake import REGS,PHASE_MASK

IMAGE_SHA='5fd498a9c4718c1da412296b04013ffc6833172b19adc1c99d32d1fc37505b5f'
HEX_SHA='8d791be4b903d2b7514a9d31338236d917ff3d8ce23f4e6b81bca9a0e1099ec2'
OLD_SHA='697f787d3cff0f960db70a7f487aa490012732561c4cea8fc5192e0d988e4f18'
OLD_BYTES=50456
IMAGE_BYTES=50496


def validate(a):
    if not getattr(a,'authorized_startup_review',False):raise ValueError('Single bounded startup diagnosis scope required')
    b=Path(a.build);s=json.loads((b/'summary.json').read_text(encoding='utf-8'))
    if (s['build_id']!=IDENTITY or not s['passed'] or s['bin_sha256']!=IMAGE_SHA or
        hashlib.sha256((b/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA or
        hashlib.sha256((b/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA or
        s['startup_review']['maximum_motion_seconds']!=5 or s['binary_bytes']!=IMAGE_BYTES):
        raise ValueError('Only exact frozen-startup v9 image accepted')
    if (getattr(a,'gain_mode','baseline')!='baseline' or getattr(a,'ki_probe_sign',0) or
        getattr(a,'apply_shadow_kp',False) or getattr(a,'shadow_port',None)):
        raise ValueError('Fixed baseline only')
    return s


def read_trace(a,summary):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    nm=subprocess.run([a.nm,'--defined-only',str(Path(a.build)/'speedloop-pi-review.elf')],
                      capture_output=True,text=True,check=True)
    sy={s[2]:int(s[0],16) for line in nm.stdout.splitlines() if len(s:=line.split())==3}
    session=ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',
        connect_mode='attach',frequency=1000000,no_config=True,blocking=False,
        options={'resume_on_disconnect':False,'cache.enable_memory':False,'cache.enable_register':False})
    if session is None:raise RuntimeError('No selected probe for stopped trace readback')
    with session:
        t=session.target;regs={k:t.read32(v) for k,v in REGS.items()}
        if (t.get_state()!=Target.State.HALTED or regs['tim1_bdtr']&0x8000 or regs['tim1_ccer']&PHASE_MASK or
            regs['gpioa_moder']&0x3f0000!=0x150000 or regs['gpiob_moder']&0xfc000000!=0x54000000 or
            regs['gpioa_odr']&0x700 or regs['gpiob_odr']&0xe000 or
            hashlib.sha256(bytes(t.read_memory_block8(0x08000000,summary['binary_bytes']))).hexdigest()!=IMAGE_SHA):
            raise RuntimeError('Stopped exact-image state not verified; no trace read')
        data=dict(schema_version=1,firmware_id=IDENTITY,bin_sha256=IMAGE_SHA,
                  read_only=True,no_reset=True,core_halted=True,phase_outputs_closed=True,records={},overflow={})
        layouts={'hall':('<QIIf4B',('t_us','raw_timer_ticks','period_us','rpm','hall_code','previous_code','model_stage','valid')),
                 'state':('<QfffffI',('t_us','speed_rpm','hall_theta','open_theta','iq_reference','pi_integral','model_stage'))}
        for kind,(layout,fields) in layouts.items():
            singular='hall' if kind=='hall' else 'state'
            array='hall' if kind=='hall' else 'states'
            prefix='motor_td3_g431_startup_'+singular
            count=t.read32(sy[prefix+'_count']);overflow=t.read32(sy[prefix+'_overflow'])
            if count>128:raise RuntimeError('Frozen startup trace count invalid')
            size=struct.calcsize(layout)
            data['records'][kind]=[dict(zip(fields,struct.unpack(layout,bytes(
                t.read_memory_block8(sy['motor_td3_g431_startup_'+array]+i*size,size))))) for i in range(count)]
            data['overflow'][kind]=overflow
        angle_symbol='motor_td3_g431_startup_selected_angles'
        if angle_symbol in sy:
            count=len(data['records']['state'])
            angles=struct.unpack('<'+'f'*count,bytes(t.read_memory_block8(sy[angle_symbol],count*4)))
            for row,angle in zip(data['records']['state'],angles):row['actual_selected_angle']=angle
        (Path(a.output)/'startup-trace.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        return data


def run(a):
    summary=validate(a)
    if a.phase=='flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):return flash.flash(a)
    if a.phase=='prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA):return prepare.prepare(a)
    if a.phase!='trial':raise ValueError('Unknown phase')
    a.gain_mode='baseline';a.ki_probe_sign=0;a.apply_shadow_kp=False
    with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,STOP_SECONDS=4.8,
        GAIN_CUTOFF_SECONDS=4.7,FINAL_GAIN_SECONDS=4.72,FINAL_GAIN_DEADLINE_SECONDS=4.75,
        MAX_MOTION_SECONDS=5,CAPTURE_SECONDS=7,TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing'):
        report=trial.trial(a)
    report.update(runtime_profile='single-5s-startup-trace-v1',actor_applied=False,
        ordinary_deployment_allowed=False,performance_claim_allowed=False)
    try:
        if report.get('core_halted_after_physical_shutdown'):
            data=read_trace(a,summary)
            report['startup_trace_counts']={k:len(v) for k,v in data['records'].items()}
            report['startup_trace_overflow']=data['overflow']
            report['startup_trace_readback_passed']=not any(data['overflow'].values())
        else:report['startup_trace_readback_passed']=False
    except Exception as e:report['passed']=False;report['startup_trace_error']=str(e)
    (Path(a.output)/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(report,allow_nan=False));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--authorized-startup-review',action='store_true')
    p.add_argument('--gain-mode',default='baseline')
    for name in ('nm','boot-token-file','pyocd','pack'):p.add_argument('--'+name)
    for name in ('energized-update-authorized','power-disconnected-confirmed','energized-phase-inhibited-confirmed',
                 'power-confirmed','authorized-no-thermal-trial'):p.add_argument('--'+name,action='store_true')
    a=p.parse_args();required={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,k) for k in required[a.phase]):p.error('Missing phase-specific paths')
    raise SystemExit(0 if run(a)['passed'] else 1)
