"""Exact v3 -> reviewed v4 Flash update, with the user's energized exception.

Checks the old full image and six GPIO-low phase gates before any reset. Explicit
SYSRESETREQ/halt precedes programming. Does not create a session or start motion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from speedloop_motion_handshake import REGS, PHASE_MASK, IDENTITY
from speedloop_motion_prepare import ENERGIZED_IMAGE_SHA

OLD_SHA='7128a27aad687c31a3bc26c2734eb6ea3d79cc96922addf0b2f6319d25fd3c93'


def flash(a):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    build, output=Path(a.build).resolve(),Path(a.output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents:
        raise ValueError('Output outside approved temporary root')
    if not a.energized_update_authorized:
        raise ValueError('User exception for energized programming required')
    output.mkdir(parents=True,exist_ok=True)
    info=json.loads((build/'summary.json').read_text(encoding='utf-8'))
    if info['build_id']!=IDENTITY or not info['passed'] or info['bin_sha256']!=ENERGIZED_IMAGE_SHA:
        raise ValueError('Wrong v4 build')
    def session():
        return ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',
            connect_mode='attach',frequency=1000000,no_config=True,blocking=False,
            options={'resume_on_disconnect':False})
    report=dict(passed=False,hardware_accessed=True,firmware_id=IDENTITY,
                energized_update_exception=True,motion_started=False,bin_sha256=ENERGIZED_IMAGE_SHA)
    first=session()
    if first is None: raise RuntimeError('Selected STLink is disconnected; no reset/programming')
    with first as s:
        target=s.target
        old=bytes(target.read_memory_block8(0x08000000,49148))
        values={name:target.read32(addr) for name,addr in REGS.items()}
        if (hashlib.sha256(old).hexdigest()!=OLD_SHA or
            values['device_id']&0xfff!=0x468 or values['tim1_bdtr']&0x8000 or
            values['tim1_ccer']&PHASE_MASK or values['gpioa_moder']&0x3f0000!=0x150000 or
            values['gpiob_moder']&0xfc000000!=0x54000000 or
            values['gpioa_odr']&0x700 or values['gpiob_odr']&0xe000):
            raise RuntimeError('Unrecognized old image or gate state; no reset/programming')
        report['pre_reset_state']=values
        (output/'previous-private.bin').write_bytes(old)
        target.halt() # Output inhibition above is verified before halting.
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.read32(REGS['tim1_bdtr'])&0x8000 or target.read32(REGS['tim1_ccer'])&PHASE_MASK:
            raise RuntimeError('Reset did not disable TIM1 outputs')
    cmd=[sys.executable,'-B',a.pyocd,'load','--no-config','--pack',a.pack,'-t','STM32G431CBTx',
         '-u',a.uid,'-f','1M','-M','attach','--no-reset','--format','hex',str(build/'speedloop-pi-review.hex')]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
    (output/'programming.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
    with session() as s:
        target=s.target
        target.halt()
        target.write32(REGS['tim1_bdtr'],target.read32(REGS['tim1_bdtr'])&~0x8000)
        target.write32(REGS['tim1_ccer'],target.read32(REGS['tim1_ccer'])&~PHASE_MASK)
        for base,pins,mask,mode in ((0x48000000,0x700,0x3f0000,0x150000),
                                   (0x48000400,0xe000,0xfc000000,0x54000000)):
            target.write32(base+0x18,pins<<16)
            target.write32(base,(target.read32(base)&~mask)|mode)
        image=bytes(target.read_memory_block8(0x08000000,info['binary_bytes']))
        readback=hashlib.sha256(image).hexdigest()
        report.update(full_readback_sha256=readback,core_halted=True,
                      final_state={n:target.read32(addr) for n,addr in REGS.items()},binary_bytes=len(image))
        report['passed']=result.returncode==0 and readback==ENERGIZED_IMAGE_SHA
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','output','pyocd','pack'):p.add_argument('--'+key,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--energized-update-authorized',action='store_true')
    a=p.parse_args();raise SystemExit(0 if flash(a)['passed'] else 1)
