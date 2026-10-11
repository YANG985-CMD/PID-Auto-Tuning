"""Prepare one motion-v3 identity while motor power is physically disconnected.

Does not flash or start the motor. Verifies the full image, resets with explicit
SYSRESETREQ, stops at main AFTER C initialization, writes one unique token,
observes phase-inhibited ADC startup, and leaves the core halted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import struct
import subprocess
import time

from speedloop_motion_handshake import IDENTITY,PHASE_MASK,REGS,RAM


def prepare(a):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    output=Path(a.output).resolve();build=Path(a.build).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents:
        raise ValueError('Output must be under the approved temporary root')
    if not a.power_disconnected_confirmed:
        raise ValueError('Physical motor-power disconnection must be confirmed')
    output.mkdir(parents=True,exist_ok=True)
    summary=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if summary['build_id']!=IDENTITY or not summary['passed'] or not summary['motion_capable']:
        raise ValueError('Unexpected motion build')
    nm=subprocess.run([a.nm,'--defined-only',str(build/'speedloop-pi-review.elf')],capture_output=True,text=True,check=True)
    symbols={line.split()[2]:int(line.split()[0],16) for line in nm.stdout.splitlines() if len(line.split())==3}
    main=symbols['main']&~1;token_address=symbols['motor_td3_g431_debugger_boot_token']
    boot=secrets.randbits(64) or 1
    report={'schema_version':1,'firmware_id':IDENTITY,'passed':False,'hardware_accessed':True,
            'motor_power_physically_disconnected':True,'begin_sent':False,'gains_sent':False}
    session=ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',
        connect_mode='attach',frequency=1000000,options={'resume_on_disconnect':False},no_config=True)
    if session is None:raise RuntimeError('No selected debug probe')
    with session:
        target=session.target
        try:
            target.halt()
            image=bytes(target.read_memory_block8(0x08000000,summary['binary_bytes']))
            if hashlib.sha256(image).hexdigest()!=summary['bin_sha256']:
                raise RuntimeError('Full Flash image mismatch; no reset/token write')
            report['full_readback_sha256']=summary['bin_sha256']
            target.reset_and_halt(Target.ResetType.SW_SYSRESETREQ)
            if not target.set_breakpoint(main):raise RuntimeError('Could not set main breakpoint')
            target.resume();due=time.monotonic()+1
            while time.monotonic()<due and target.get_state()!=Target.State.HALTED:time.sleep(.01)
            if target.get_state()!=Target.State.HALTED or target.read_core_register('pc')!=main:
                raise RuntimeError('Did not stop at main after C initialization')
            target.write_memory_block8(token_address,list(struct.pack('<Q',boot)))
            if bytes(target.read_memory_block8(token_address,8))!=struct.pack('<Q',boot):
                raise RuntimeError('Boot-token write mismatch')
            target.remove_breakpoint(main);target.resume();time.sleep(.5);target.halt()
            values={name:target.read32(address) for name,address in REGS.items()}
            for name in RAM:
                values[name]=target.read8(symbols[name]) if name in ('Motor_state','ADC_offset') else target.read32(symbols[name])
            if (values['device_id']&0xfff!=0x468 or values['tim1_ccer']&PHASE_MASK or
                not values['tim1_bdtr']&0x8000 or values['gpioa_moder']&0x3f0000!=0x150000 or
                values['gpiob_moder']&0xfc000000!=0x54000000 or values['endpoint_ready']!=1 or
                values['initialized']!=1 or values['irq_fault'] or values['Motor_state'] or
                values['ADC_offset']!=1 or values['adc_samples']<100 or
                any(target.read_memory_block8(token_address,8))):
                raise RuntimeError('Startup sampling or phase-inhibited state failed')
            report.update(passed=True,startup_state=values,core_halted=True,
                          boot_token_consumed=True,run_seconds=.5)
            (output/'boot-token.txt').write_text(f'{boot:016x}\n',encoding='ascii')
        except Exception as exc:
            report['error']=str(exc)
        finally:
            target.halt()
            target.remove_breakpoint(main)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--power-disconnected-confirmed',action='store_true')
    args=p.parse_args();raise SystemExit(0 if prepare(args)['passed'] else 1)
