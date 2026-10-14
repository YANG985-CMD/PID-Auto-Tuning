"""Synthetic stitching tests; fixtures never enter real motor replay."""
import copy
import unittest
from stitch_speedloop_replay import extend
from speedloop_response_windows import build_trial
from test_speedloop_response_windows import example


def fixture():
    c,t=example()
    for r in c:
        r["telemetry_seq_start"]=r["t_state_us"]//20000
        r["observation"]=r["state"]
    for r in t:r["applied_seq"]=1
    kept,_=build_trial(c,t)
    return kept,t


class StitchChecks(unittest.TestCase):
    def test_extends_only_measured_hold(self):
        rs,t=fixture();r,reason=extend(rs[0],rs[2],t)
        self.assertIsNone(reason)
        self.assertEqual(r["next_state"],rs[2]["state"])
        self.assertEqual(r["t_next_us"],rs[2]["t_state_us"])
        self.assertEqual(r["source_command_seqs"],rs[0]["source_command_seqs"])
        self.assertEqual(r["t_apply_us"],rs[0]["t_apply_us"])
        self.assertEqual(r["action_normalized"],rs[0]["action_normalized"])
        self.assertFalse(set(r["response_telemetry_seqs"]) & set(rs[2]["response_telemetry_seqs"]))

    def test_different_intermediate_gain_refused(self):
        rs,t=fixture();t[6]["ki"]+=.000036
        r,reason=extend(rs[0],rs[2],t)
        self.assertIsNotNone(reason);self.assertEqual(r,rs[0])

    def test_missing_raw_packet_rejected(self):
        rs,t=fixture();t.pop(6)
        with self.assertRaises(AssertionError):extend(rs[0],rs[2],t)

    def test_cross_boot_rejected(self):
        rs,t=fixture();following=copy.deepcopy(rs[2]);following["boot_id"]="another-synthetic-boot"
        with self.assertRaises(AssertionError):extend(rs[0],following,t)

    def test_stopped_interval_refused(self):
        rs,t=fixture();t[6]["enabled"]=False
        _,reason=extend(rs[0],rs[2],t);self.assertIsNotNone(reason)


if __name__=="__main__":unittest.main()
