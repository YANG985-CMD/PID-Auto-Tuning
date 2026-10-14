import argparse
import json
from pathlib import Path
import unittest
from build_speedloop_reference_replay import reference_for_window


class ReferenceTest(unittest.TestCase):
    def window(self,source,responses):
        return dict(state_history=[dict(speed_ref=source)]*3,
            response=[dict(speed_ref=v) for v in responses])

    def test_actual_constant_reference_is_retained(self):
        for ref in (950.,1000.,1050.):
            self.assertEqual(reference_for_window(self.window(ref,[ref]*4),{950.,1000.,1050.}),ref)

    def test_step_in_source_history_or_response_is_excluded(self):
        self.assertIsNone(reference_for_window(self.window(1000.,[950.]*4),{950.,1000.,1050.}))
        self.assertIsNone(reference_for_window(self.window(1000.,[1000.,1000.,1050.,1050.]),{950.,1000.,1050.}))
        w=self.window(1000.,[1000.]*4);w['state_history'][0]['speed_ref']=950.
        self.assertIsNone(reference_for_window(w,{950.,1000.,1050.}))

    def test_unknown_reference_cannot_be_hidden_as_crossing(self):
        for value in (0.,1100.,float('nan')):
            with self.assertRaises(ValueError):reference_for_window(self.window(1000.,[1000.,value]),{950.,1000.,1050.})

    def test_old_fixed_reference_scope_cannot_accept_excitation(self):
        with self.assertRaises(ValueError):reference_for_window(self.window(950.,[950.]*4),{1000.})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReferenceTest))
    (out/'summary.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,hardware_accessed=False))+'\n')
    raise SystemExit(0 if r.wasSuccessful() else 1)
