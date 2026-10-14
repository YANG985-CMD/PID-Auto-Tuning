import unittest
from speedloop_segment_probe import PATTERN,SegmentProbe
from speedloop_stream_training import INTERIOR_GAINS,KI


class Checks(unittest.TestCase):
    def test_each_reference_segment_has_each_gain_and_complete_positions(self):
        self.assertEqual([PATTERN.count(g) for g in range(3)],[5,5,5])
        for phase in range(3):
            self.assertEqual(sorted([sum(PATTERN[i]==g for i in range(phase,15,3)) for g in range(3)]),[1,2,2])
        for cycle in range(5):self.assertEqual(sorted(PATTERN[cycle*3:cycle*3+3]),[0,1,2])
    def test_first_and_last_boundaries_and_pre_reference_command(self):
        p=SegmentProbe();self.assertEqual(p.planned(3849,mode='kp_probe'),(INTERIOR_GAINS[0],KI))
        for s,label in enumerate(PATTERN):
            self.assertEqual(p.planned(3850+s*1200,mode='kp_probe'),(INTERIOR_GAINS[label],KI))
            self.assertEqual(p.decisions[-1]['planned_reference_begin_ms'],4000+s*1200)
        self.assertEqual(p.planned(21990,mode='kp_probe'),(INTERIOR_GAINS[PATTERN[-1]],KI))
        self.assertEqual(p.planned(22000,mode='kp_probe'),(INTERIOR_GAINS[0],KI))
    def test_missing_segment_and_ki_change_rejected(self):
        p=SegmentProbe();p.planned(3850,mode='kp_probe')
        with self.assertRaises(RuntimeError):p.planned(6300,mode='kp_probe')
        with self.assertRaises(ValueError):p.planned(4000,ki_probe_sign=1,mode='kp_probe')


if __name__=='__main__':unittest.main()
