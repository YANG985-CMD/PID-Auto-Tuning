"""Offline declared schedule/range checks. Does not import CAN or open hardware."""
import argparse,json
from pathlib import Path
from types import SimpleNamespace
import speedloop_extended_hold_v28 as r
from speedloop_duration_review import overrides

def test(output):
    output=Path(output);assert not output.exists();output.mkdir(parents=True)
    simulated=[]
    for index in (0,1):
        cfg=r.expected_schedule(index);assert len(cfg['pattern'])==32
        assert cfg['reserved_motion_seconds']==24 and cfg['maximum_batch_motion_seconds']==48
        assert cfg['minimum_cooldown_seconds']==30 and cfg['nominal_target_hold_ms']==2000
        assert all(4<=level<=16 for level in cfg['pattern'])
        for at in range(0,32,4):assert len(set(cfg['pattern'][at:at+4]))==1
        with overrides(r.base,PATTERNS=r.PATTERNS):
            probe=r.ExtendedProbe(r.PATTERNS[index]);actual=r.LEVELS[r.BASE_INDEX];slots=set()
            for elapsed in range(0,23201,50):
                probe.observe(dict(enabled=True,applied_seq=1,kp=actual,ki=r.KI))
                gain,ki=probe.planned(elapsed)
                assert ki==r.KI and abs(gain-actual)<=.00013556+1e-9
                actual=gain
                if r.PLATEAU_START_MS<=elapsed<r.PLATEAU_END_MS:
                    slot=(elapsed-r.PLATEAU_START_MS)//500;slots.add(slot)
                    assert gain==r.LEVELS[r.PATTERNS[index][slot]]
            assert slots==set(range(32)) and actual==r.LEVELS[r.BASE_INDEX]
            simulated.append(dict(index=index,all_slots_covered=True,host_step_retained=True,final_baseline=True))
    rejected=[]
    for label,operation in (
        ('missing-scope',lambda:r.run(SimpleNamespace(phase='trial'))),
        ('flash-forbidden',lambda:r.run(SimpleNamespace(phase='flash',authorized_extended_hold_capture=True))),
        ('qualify-forbidden',lambda:r.run(SimpleNamespace(phase='qualify',authorized_extended_hold_capture=True))),
        ('new-low31-source-forbidden',lambda:r.ExtendedProbe(r.PATTERNS[0]).observe(dict(enabled=True,applied_seq=1,kp=r.LEVELS[0],ki=r.KI))),
        ('Ki-change-forbidden',lambda:r.ExtendedProbe(r.PATTERNS[0]).planned(6250,ki_probe_sign=1))):
        try:operation()
        except (ValueError,RuntimeError):rejected.append(label)
        else:raise AssertionError(label)
    p=r.ExtendedProbe(r.PATTERNS[0]);p.planned(6250)
    try:p.planned(7251)
    except RuntimeError:rejected.append('missed-slot-forbidden')
    else:raise AssertionError('Missed slot must stop')
    report=dict(passed=True,simulated_rounds=simulated,rejected=rejected,
        checks=8,source_sha256=r.sha(r.__file__),exact_existing_image_sha256=r.IMAGE_SHA,
        firmware_guards_modified=False,Ki_fixed=r.KI,actor_applied=False,
        hardware_accessed=False,deployment_allowed=False,performance_claim_allowed=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();test(a.output)
