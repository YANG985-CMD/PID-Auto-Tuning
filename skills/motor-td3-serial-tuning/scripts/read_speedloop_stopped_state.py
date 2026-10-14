"""Read-only exact v12 stop-state snapshot; no reset, resume or CAN owner."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
from speedloop_excitation_evidence import IMAGE_SHA,IDENTITY,IMAGE_BYTES
from speedloop_motion_handshake import REGS,PHASE_MASK


def run(a):
    identity,image_sha,image_bytes=IDENTITY,IMAGE_SHA,IMAGE_BYTES
    if getattr(a,'profile','v12')=='v13':
        from speedloop_continuous import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v14':
        from speedloop_interior import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v15':
        from speedloop_lower_commission import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v16':
        from speedloop_ki_response import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v17':
        from speedloop_snapshot_response import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v18':
        from speedloop_sampling_response import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v19':
        from speedloop_lower8_response import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v20':
        from speedloop_fixedref_probe import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v21':
        from speedloop_lower16_probe import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v22':
        from speedloop_sampling_v22 import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v23':
        from speedloop_reference_v23 import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v24':
        from speedloop_upper8_probe import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v25':
        from speedloop_upper8_continuous import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v26':
        from speedloop_upper8_reference_v26 import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v27':
        from speedloop_bidirectional_v27 import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    elif getattr(a,'profile','v12')=='v28':
        from speedloop_lower31_v28 import IDENTITY as cid,IMAGE_SHA as csha,IMAGE_BYTES as cbytes
        identity,image_sha,image_bytes=cid,csha,cbytes
    out=Path(a.output).resolve();build=Path(a.build).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in out.parents:raise ValueError('Use task temporary root')
    info=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if info['build_id']!=identity or info['bin_sha256']!=image_sha or info['binary_bytes']!=image_bytes:
        raise ValueError('Unexpected image before hardware import')
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    nm=subprocess.run([a.nm,'--defined-only',str(build/'speedloop-pi-review.elf')],capture_output=True,text=True,check=True)
    symbols={s[2]:int(s[0],16) for line in nm.stdout.splitlines() if len(s:=line.split())==3}
    session=ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',connect_mode='attach',
        frequency=1000000,no_config=True,blocking=False,options={'resume_on_disconnect':False,
        'cache.enable_memory':False,'cache.enable_register':False})
    if session is None:raise RuntimeError('Selected probe unavailable')
    with session:
        target=session.target
        image=bytes(target.read_memory_block8(0x08000000,image_bytes))
        values={name:target.read32(address) for name,address in REGS.items()}
        halted=target.get_state()==Target.State.HALTED
        fault=target.read32(symbols['irq_fault']);tx=target.read32(symbols['motor_td3_g431_tx_fault'])
        motor=target.read8(symbols['Motor_state'])
        # Scalars retain the actual latched evidence; no inferred fault cause.
        diagnostic={}
        for name in ('initialized','endpoint_ready','motion_enabled','adc_samples',
                     'hall_bad','ring_write','ring_read','motor_td3_g431_hall_edge_count'):
            if name in symbols: diagnostic[name]=target.read32(symbols[name])
        for name in ('now_us','main_seen_us','adc_seen_us','bus_seen_us',
                     'motor_td3_g431_debugger_boot_token'):
            if name in symbols:
                diagnostic[name]=struct.unpack('<Q',bytes(target.read_memory_block8(symbols[name],8)))[0]
        if 'motor_td3_g431_trial_timing' in symbols:
            vals=struct.unpack('<QQQIII',bytes(target.read_memory_block8(symbols['motor_td3_g431_trial_timing'],36)))
            diagnostic['trial_timing']=dict(zip(('started_us','run_started_us','last_us','started','run_seen','fault'),vals))
        passed=(hashlib.sha256(image).hexdigest()==image_sha and halted and not fault and not tx and motor==0
            and values['device_id']&0xfff==0x468 and not values['tim1_ccer']&PHASE_MASK
            and not values['tim1_bdtr']&0x8000 and values['gpioa_moder']&0x3f0000==0x150000
            and values['gpiob_moder']&0xfc000000==0x54000000
            and not values['gpioa_odr']&0x700 and not values['gpiob_odr']&0xe000)
        report=dict(passed=bool(passed),hardware_accessed=True,hardware_written=False,reset=False,resume=False,
            firmware_id=identity,full_readback_sha256=hashlib.sha256(image).hexdigest(),core_halted=halted,
            irq_fault=fault,tx_fault=tx,Motor_state=motor,registers=values,diagnostic=diagnostic,
            fault_cause_verified=False)
    out.mkdir(parents=True,exist_ok=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--profile',choices=('v12','v13','v14','v15','v16','v17','v18','v19','v20','v21','v22','v23','v24','v25','v26','v27','v28'),default='v12')
    a=p.parse_args();raise SystemExit(0 if run(a)['passed'] else 1)
