"""Stopped exact v23 read-clock qualification; no reset/resume/app writes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from statistics import mean
from speedloop_reference_v23 import IMAGE_SHA,IMAGE_BYTES,IDENTITY
from speedloop_motion_handshake import REGS,PHASE_MASK


def run(a):
    output=Path(a.output);assert not output.exists()
    assert Path('E:/simulink/_codex_tmp').resolve() in output.resolve().parents
    info=json.loads((Path(a.build)/'summary.json').read_text())
    if info['bin_sha256']!=IMAGE_SHA or info['build_id']!=IDENTITY:raise ValueError('Unknown image')
    nm=subprocess.run([a.nm,'--defined-only',str(Path(a.build)/'speedloop-pi-review.elf')],capture_output=True,text=True,check=True)
    symbols={s[2]:int(s[0],16) for line in nm.stdout.splitlines() if len(s:=line.split())==3}
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    rows=[];reference={}
    for frequency in (1000000,4000000):
        session=ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',
            connect_mode='attach',frequency=frequency,no_config=True,blocking=False,
            options={'resume_on_disconnect':False,'cache.enable_memory':False,'cache.enable_register':False})
        if session is None:raise RuntimeError('Probe unavailable')
        with session:
            target=session.target
            image=bytes(target.read_memory_block8(0x08000000,IMAGE_BYTES))
            gates={name:target.read32(address) for name,address in REGS.items()}
            if (target.get_state()!=Target.State.HALTED or hashlib.sha256(image).hexdigest()!=IMAGE_SHA
                or target.read32(symbols['irq_fault']) or target.read32(symbols['motor_td3_g431_tx_fault'])
                or target.read8(symbols['Motor_state']) or target.read32(symbols['initialized'])!=1
                or gates['tim1_ccer']&PHASE_MASK
                or gates['gpioa_moder']&0x3f0000!=0x150000 or gates['gpiob_moder']&0xfc000000!=0x54000000
                or gates['gpioa_odr']&0x700 or gates['gpiob_odr']&0xe000):
                raise RuntimeError('Need initialized exact v23, core halted and six outputs low')
            for count in (4,8,12):
                values=[];identical=True
                for _ in range(100):
                    started=time.perf_counter()
                    blob=bytes(target.read_memory_block8(symbols['motor_td3_g431_hall_edges'],count*24))
                    values.append((time.perf_counter()-started)*1000)
                    if count not in reference:reference[count]=blob
                    identical=identical and blob==reference[count]
                rows.append(dict(frequency_hz=frequency,records=count,samples=100,
                    mean_ms=mean(values),maximum_ms=max(values),over_6ms=sum(v>6 for v in values),
                    content_identical=identical,sha256=hashlib.sha256(reference[count]).hexdigest()))
            if target.get_state()!=Target.State.HALTED:raise RuntimeError('Core changed during reads')
    report=dict(passed=all(r['content_identical'] and r['over_6ms']==0 for r in rows if r['frequency_hz']==4000000),
        rows=rows,firmware_sha256=IMAGE_SHA,firmware_id=IDENTITY,core_halted=True,
        hardware_written=False,application_memory_or_peripheral_writes=False,
        debugger_clock_configured=True,reset=False,resume=False,motion_started=False,
        six_phase_outputs_gpio_low=True,sampling_channel4_moe=bool(gates['tim1_bdtr']&0x8000),
        phase_gpio_modes_verified_as_outputs_not_timer_alternate_function=True)
    output.mkdir(parents=True);(output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841');a=p.parse_args()
    raise SystemExit(0 if run(a)['passed'] else 1)
