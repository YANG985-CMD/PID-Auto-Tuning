import unittest
from audit_speedloop_context_support import analyze


def fixture():
    return [dict(slot=i,reference_phase=i%9//3,level=(i//9+i%3)%3,
                 response_mse_rpm2=100,source_error_rpm=0) for i in range(45)]


class Checks(unittest.TestCase):
    def test_balanced_common_contexts_preserve_equal_scores(self):
        report=analyze(fixture())
        self.assertTrue(report['all_gain_levels_supported_in_all_contexts'])
        self.assertEqual(report['exploratory_common_context_rmse_rpm'],[10,10,10])
        self.assertFalse(report['actor_admission'])
    def test_missing_cell_is_explicit_and_not_filled(self):
        rows=fixture()
        for r in rows:
            if r['reference_phase']==1 and r['slot']%3==2 and r['level']==1:r['level']=0
        report=analyze(rows)
        self.assertFalse(report['all_gain_levels_supported_in_all_contexts'])
        self.assertEqual(report['missing_contexts'][0]['missing_gain_levels'],[1])
        self.assertFalse(report['missing_responses_synthesized'])
    def test_duplicate_slots_rejected(self):
        rows=fixture();rows[-1]['slot']=0
        with self.assertRaises(ValueError):analyze(rows)


if __name__=='__main__':unittest.main()
