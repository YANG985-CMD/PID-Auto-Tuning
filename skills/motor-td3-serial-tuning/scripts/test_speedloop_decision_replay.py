"""Actual-source decision reconstruction checks; no writes or hardware."""
import unittest
from rebuild_speedloop_decision_replay import rebuild


class Tests(unittest.TestCase):
    def test_real_decisions_link_and_cover_actions(self):
        root='E:/dianji/motor-td3-local-results/fixedref-critic-audit-20261013'
        for folder,split in (('round0','train'),('round1','validation')):
            rows,summary=rebuild(root+'/'+folder,split)
            self.assertEqual(len(rows),45);self.assertEqual(summary['actual_action_changes'],30)
            self.assertEqual(summary['actual_pair_counts'],[[5]*3]*3)
            for a,b in zip(rows,rows[1:]):self.assertEqual(a['response'][-1],b['state'])
            self.assertTrue(all(.95<r['elapsed_discount']<.98 for r in rows))
            self.assertTrue(all(r['measured_reward_span_us']<r['duration_us'] for r in rows))

    def test_split_cannot_be_changed(self):
        with self.assertRaises(ValueError):
            rebuild('E:/dianji/motor-td3-local-results/fixedref-critic-audit-20261013/round1','train')


if __name__=='__main__':unittest.main()
