"""Synthetic causality tests only; no samples are added to the real replay."""
import unittest
from speedloop_response_windows import build_trial,state,temporal_mean


def example():
    frames=[]
    for seq,t in enumerate(range(0,241000,20000)):
        frames.append(dict(seq=seq,t_us=t,enabled=True,fault=0,speed_ref=1000,
                           speed=990,error_history=10,integral_output=.1,current=.2,
                           vbus=24,kp=.003389,ki=.00144,elapsed_ms=t/1000))
    candidates=[]
    for index,(start,end) in enumerate(((0,80000),(80000,160000),(160000,240000))):
        s,n=frames[start//20000],frames[end//20000]
        candidates.append(dict(stage_confirmed_from_raw_edges=True,learner_eligible=False,
            t_state_us=start,t_apply_us=start+40000,t_next_us=end,
            state=state(s),next_state=state(n),next_observation=state(n),
            action_applied=[s["kp"],s["ki"]],action_normalized=[0,0],
            boot_id="synthetic-test-only",run_index=1,command_seq=index+1,
            telemetry_seq_end=n["seq"],reward=-.01))
    return candidates,frames


class ResponseWindowChecks(unittest.TestCase):
    def test_hold_uses_already_read_back_gain_without_rewriting_ack(self):
        c,t=example()
        accepted,rejected=build_trial(c,t)
        self.assertEqual(len(accepted),3)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["t_effective_us"],0)
        self.assertEqual(accepted[0]["t_apply_us"],40000)
        self.assertEqual(accepted[0]["response_telemetry_seqs"],[1,2,3,4])
        self.assertEqual(accepted[0]["response_sample_count"],4)

    def test_gain_change_waits_for_actual_apply_and_merges_zero_refresh(self):
        c,t=example()
        c[0]["state"][8]=.001404
        t[0]["ki"]=.001404
        t[1]["ki"]=.001404
        c[0]["action_normalized"]=[0,.25]
        accepted,rejected=build_trial(c,t)
        self.assertEqual(accepted[0]["t_effective_us"],40000)
        self.assertEqual(accepted[0]["source_command_seqs"],[1,2])
        self.assertTrue(all(seq>=3 for seq in accepted[0]["response_telemetry_seqs"]))
        self.assertEqual(accepted[0]["action_normalized"],[0,.25])
        self.assertFalse(rejected)

    def test_truncated_or_faulted_record_not_accepted(self):
        c,t=example()
        c[0]["stage_confirmed_from_raw_edges"]=False
        with self.assertRaises(AssertionError): build_trial(c,t)
        c,t=example();t[-1]["fault"]=8
        with self.assertRaises(AssertionError): build_trial(c,t)

    def test_frame_gap_and_wrong_readback_rejected(self):
        c,t=example();t.pop(2)
        with self.assertRaises(AssertionError): build_trial(c,t)
        c,t=example();t[1]["ki"]+=.00001
        with self.assertRaises(AssertionError): build_trial(c,t)

    def test_nonzero_repeated_target_not_relabeled(self):
        c,t=example()
        c[0]["action_normalized"]=[0,.25];c[0]["state"][8]=.001404;t[0]["ki"]=.001404
        c[1]["action_normalized"]=[0,.25]
        with self.assertRaises(AssertionError): build_trial(c,t)

    def test_episodes_cannot_be_merged(self):
        c,t=example();c[1]["boot_id"]="other"
        with self.assertRaises(AssertionError): build_trial(c,t)

    def test_time_weighted_response_known_value(self):
        self.assertAlmostEqual(temporal_mean([0,2,4],[0,10,30]),7/3)

    def test_no_response_sample_overlap(self):
        c,t=example()
        accepted,_=build_trial(c,t)
        ids=[seq for r in accepted for seq in r["response_telemetry_seqs"]]
        self.assertEqual(len(ids),len(set(ids)))

    def test_known_hold_between_nonadjacent_candidates_can_be_observed(self):
        c,t=example();c.pop(1)
        accepted,_=build_trial(c,t,min_observed_ms=100)
        self.assertEqual(accepted[0]["source_command_seqs"],[1,3])
        self.assertEqual(len(accepted[0]["response_telemetry_seqs"]),12)

    def test_unknown_gain_in_gap_cannot_be_merged(self):
        c,t=example();c.pop(1);t[6]["ki"]+=.000036
        accepted,rejected=build_trial(c,t,min_observed_ms=100)
        self.assertFalse(accepted)
        self.assertEqual(len(rejected),2)


if __name__=="__main__":
    unittest.main()
