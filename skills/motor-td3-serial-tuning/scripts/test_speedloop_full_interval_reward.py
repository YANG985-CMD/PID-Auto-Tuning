import argparse,copy,json,tempfile,unittest
from pathlib import Path
import audit_speedloop_full_interval_reward as subject


class IntervalTest(unittest.TestCase):
    def test_independent_partial_interval_integral(self):
        records=[dict(edge=i+1,t_us=i*10,period_us=10,rpm=rpm,valid=True,model_stage=4)
            for i,rpm in enumerate((900,950,1000,1050))]
        r=subject.integrate(records,[0,10,20,30],5,25,950)
        self.assertEqual(r['duration_us'],20);self.assertEqual(r['mse_rpm2'],1250)
        self.assertEqual(r['peak_speed_rpm'],1000)
        with self.assertRaises(ValueError):subject.integrate(records,[0,10,20,30],-1,25,950)
        with self.assertRaises(ValueError):subject.integrate([records[0],*records[2:]],[0,20,30],5,25,950)

    def test_fault_boundary_gain_reference_and_missing_proof_rejected(self):
        p=copy.deepcopy(self.row['packets'][0]);proof=self.row['stage_proofs'][0]
        w=json.loads(Path(self.row['source_window_file']).read_text())
        event_path=Path(self.row['raw_window_file']).parent.parent/'stream/events.jsonl'
        events=[json.loads(s) for s in event_path.read_text().splitlines()]
        commands={e['command']['command_seq']:e['command'] for e in events
            if e['kind']=='command' and e['command']['type']=='gains'}
        subject.validate_packet(p,proof,commands,w)
        for field,value in (('fault',1),('kp',.02),('speed_ref',1200),('current',2),('vbus',17),('speed',float('nan'))):
            bad=copy.deepcopy(p);bad[field]=value
            with self.assertRaises(ValueError):subject.validate_packet(bad,proof,commands,w)
        with self.assertRaises(ValueError):subject.validate_packet(p,None,commands,w)
        bad=copy.deepcopy(commands);bad[p['applied_seq']]['expires_us']=p['t_apply_us']-1
        with self.assertRaises(ValueError):subject.validate_packet(p,proof,bad,w)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False);tempfile.tempdir=str(out)
    with Path(a.rows).open() as f:IntervalTest.row=json.loads(next(f))
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IntervalTest))
    (out/'summary.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,hardware_accessed=False,deployment_allowed=False))+'\n')
    raise SystemExit(0 if r.wasSuccessful() else 1)
