"""Exact stopped v27 transport and actual Hall-tail reader qualification."""
import argparse,gc,json,struct,subprocess
from pathlib import Path
import benchmark_speedloop_v23_reads as previous
from speedloop_duration_review import overrides
from speedloop_bidirectional_v27 import IDENTITY,IMAGE_SHA,IMAGE_BYTES,sha

def run(a):
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,IMAGE_BYTES=IMAGE_BYTES):
        base=previous.run(a)
    if not base['passed']:raise ValueError('Raw block qualification failed; no motion retry')
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target
    from live_speedloop_hall import BoundedPipelinedHallReader
    from speedloop_motion_handshake import REGS,PHASE_MASK
    tail=json.loads(Path(a.hall_tail).read_text());assert tail['total_edges']>=8
    nm=subprocess.run([a.nm,'--defined-only',str(Path(a.build)/'speedloop-pi-review.elf')],capture_output=True,text=True,check=True)
    symbols={s[2]:int(s[0],16) for line in nm.stdout.splitlines() if len(s:=line.split())==3}
    session=ConnectHelper.session_with_chosen_probe(unique_id=a.uid,target_override='cortex_m',
        connect_mode='attach',frequency=4000000,no_config=True,blocking=False,
        options={'resume_on_disconnect':False,'cache.enable_memory':False,'cache.enable_register':False})
    if session is None:raise RuntimeError('Selected probe unavailable')
    rows=[];failures=[];collecting=gc.isenabled()
    with session:
        t=session.target;assert t.get_state()==Target.State.HALTED
        import hashlib
        assert hashlib.sha256(bytes(t.read_memory_block8(0x08000000,IMAGE_BYTES))).hexdigest()==IMAGE_SHA
        assert not t.read32(REGS['tim1_ccer'])&PHASE_MASK and not t.read32(REGS['tim1_bdtr'])&0x8000
        assert not t.read32(REGS['gpioa_odr'])&0x700 and not t.read32(REGS['gpiob_odr'])&0xe000
        count=t.read32(symbols['motor_td3_g431_hall_edge_count']);assert count==tail['total_edges']
        for i in range(1000):
            reader=BoundedPipelinedHallReader();reader.cursor=reader.read_cursor=count-8
            try:
                reader.read(t,symbols);result=reader.read(t,symbols)
                assert result['records']==tail['records'][-8:]
                rows.append(dict(sample=i,block_read_ms=reader.read_ms[0],confirmation_ms=reader.read_ms[1]))
            except RuntimeError as e:failures.append(dict(sample=i,error=str(e)))
        assert t.get_state()==Target.State.HALTED and t.read32(symbols['irq_fault'])==0
        assert t.read8(symbols['Motor_state'])==0 and gc.isenabled()==collecting
    report=dict(passed=not failures,profile='pipelined-chunk8-v2',samples=1000,complete_samples=len(rows),
        over_6ms=len(failures),failures=failures,
        maximum_block_read_ms=max((v['block_read_ms'] for v in rows),default=0),
        maximum_confirmation_ms=max((v['confirmation_ms'] for v in rows),default=0),
        firmware_sha256=IMAGE_SHA,actual_halted_v27_tail_verified=True,tail_sha256=sha(a.hall_tail),
        hardware_written=False,reset=False,resume=False,motion_started=False,GC_restored=True,
        hardware_real_time_guarantee=False)
    output=Path(a.output)/'bounded-reader-benchmark.json';assert not output.exists()
    output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','output','nm','hall-tail'):p.add_argument('--'+name,required=True)
    p.add_argument('--uid',default='0674FF554850715087183841');a=p.parse_args()
    raise SystemExit(0 if run(a)['passed'] else 1)
