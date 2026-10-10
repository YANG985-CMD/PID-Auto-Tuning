"""Offline current-fit tests; no hardware and no firmware writes."""
import argparse
import csv
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
import fit_current_calibration as fit

def rows_for(gain=0.02,offset=2048):
    rows=[]
    for phase,phase_offset in zip(fit.PHASES,(0,2,-1)):
        for current in (-2,-1,0,1,2,3):
            rows.append((phase,current,(current/gain)+offset+phase_offset))
    return rows

class FitTests(unittest.TestCase):
    def test_fits_each_phase_without_approval(self):
        result=fit.fit(rows_for())
        for phase in fit.PHASES:
            self.assertAlmostEqual(result['phases'][phase]['gain_a_per_count'],.02,places=10)
            self.assertAlmostEqual(result['phases'][phase]['zero_adc'],2048+(0,2,-1)[fit.PHASES.index(phase)],places=8)
        self.assertTrue(result['quality']['all_bipolar']);self.assertFalse(result['device_write'])
        self.assertFalse(result['current_gain_calibrated']);self.assertIsNone(result['protection_threshold_candidate'])
    def test_rejects_missing_phase_or_insufficient_levels(self):
        with self.assertRaises(ValueError):fit.fit([('A',0,2048)]*6)
        with self.assertRaises(ValueError):fit.fit([r for r in rows_for() if r[0]!='C'])
    def test_rejects_nonfinite_and_reports_rail_codes(self):
        with self.assertRaises(ValueError):fit.fit([('A',float('nan'),2048)]*6)
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'bad.csv';source.write_text('phase,reference_A,adc_code\nA,-2,4096\n',encoding='utf-8')
            with self.assertRaises(ValueError):fit.load_rows(source)
        bad=rows_for();bad[0]=('A',-2,0)
        result=fit.fit(bad)
        self.assertEqual(result['phases']['A']['rail_samples'],1)
        self.assertFalse(result['quality']['all_nonrail'])
    def test_residual_quality_is_reported(self):
        rows=rows_for();rows[0]=(rows[0][0],rows[0][1],rows[0][2]+4)
        result=fit.fit(rows);self.assertGreater(result['phases']['A']['max_abs_residual_a'],0)
        self.assertLess(result['quality']['min_r2'],1)
    def test_output_is_reproducible_and_hashes_input(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);source=td/'samples.csv';out=td/'out'
            with source.open('w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(('phase','reference_A','adc_code'))
                for row in rows_for():w.writerow(row)
            loaded=fit.load_rows(source);result=fit.fit(loaded);result['source_csv_sha256']=fit.sha(source)
            out.mkdir();(out/'fit.json').write_text(json.dumps(result),encoding='utf-8')
            self.assertEqual(result['source_csv_sha256'],fit.sha(source));self.assertTrue((out/'fit.json').is_file())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=False);a=p.parse_args()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(FitTests);r=unittest.TextTestRunner(verbosity=2).run(suite)
    if not r.wasSuccessful():raise SystemExit(1)
