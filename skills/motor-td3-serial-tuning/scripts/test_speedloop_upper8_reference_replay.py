"""Reference clock and constant-window tests, no synthetic motor claims."""
import argparse,json,unittest
from pathlib import Path
from build_speedloop_reference_replay import reference_for_window
from build_speedloop_upper8_reference_replay import validate_reference_packet,validate_source_identity,FIXED_IDENTITIES,new,old

class Checks(unittest.TestCase):
    def test_exact_prior_fixed_firmware_identity(self):
        for identity,image_sha in FIXED_IDENTITIES:
            validate_source_identity(identity,image_sha)
            validate_reference_packet(identity,dict(enabled=True,elapsed_ms=9000,speed_ref=1000))
            with self.assertRaises(ValueError):validate_source_identity(identity,'0'*64)
            with self.assertRaises(ValueError):validate_reference_packet(identity,dict(enabled=True,elapsed_ms=9000,speed_ref=950))
    def test_reference_packet_exact_clock(self):
        for ms in range(0,24001,17):
            r=new.reference_rpm(ms*1000)
            validate_reference_packet(new.IDENTITY,dict(enabled=True,elapsed_ms=ms,speed_ref=r))
    def test_wrong_clock_cannot_pass_permitted_reference_set(self):
        for identity,ms,r in [(new.IDENTITY,7000,950),(new.IDENTITY,9000,1000),(new.IDENTITY,13000,950),
                              (old.IDENTITY,9000,950),('unknown',9000,1000)]:
            with self.assertRaises(ValueError):validate_reference_packet(identity,dict(enabled=True,elapsed_ms=ms,speed_ref=r))
    def test_reference_crossing_and_unknown_are_different(self):
        for refs,expected in [([1000,1000,1000,950,950,950,950],None),([950]*7,950),([1050]*7,1050)]:
            w=dict(state_history=[dict(speed_ref=r) for r in refs[:3]],response=[dict(speed_ref=r) for r in refs[3:]])
            self.assertEqual(reference_for_window(w,{950,1000,1050}),expected)
        for r in [800,1200,float('nan'),float('inf')]:
            w=dict(state_history=[dict(speed_ref=1000)]*3,response=[dict(speed_ref=1000),dict(speed_ref=r)])
            with self.assertRaises(ValueError):reference_for_window(w,{950,1000,1050})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();output=Path(a.output)
    assert Path('E:/simulink/_codex_tmp').resolve() in output.resolve().parents;output.mkdir(exist_ok=False)
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (output/'summary.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,
        hardware_accessed=False,new_physical_data=False,TD3_training_performed=False))+'\n')
    raise SystemExit(0 if r.wasSuccessful() else 1)
