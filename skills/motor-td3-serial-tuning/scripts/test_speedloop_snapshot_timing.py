"""Offline clock uncertainty and immutable legacy-trace audit checks."""
import unittest
from audit_speedloop_snapshot_timing import snapshot_interval, inspect, capture_origin


class SnapshotTests(unittest.TestCase):
    def test_rounding_interval_covers_capture(self):
        lo,hi=snapshot_interval(dict(enabled=True,elapsed_ms=23000.3671875),700000)
        self.assertLess(lo,23700367)
        self.assertGreater(hi,23700367)
        self.assertLess(hi-lo,16)

    def test_idle_and_nan_rejected(self):
        for p in (dict(enabled=False,elapsed_ms=1),dict(enabled=True,elapsed_ms=float('nan'))):
            with self.assertRaises(ValueError): snapshot_interval(p,0)

    def test_begin_readback_origin_is_distinct_from_later_hook(self):
        self.assertEqual(capture_origin([dict(enabled=False),dict(enabled=True,applied_seq=0,t_apply_us=500)]),500)
        with self.assertRaises(ValueError): capture_origin([dict(enabled=True,applied_seq=1,t_apply_us=550)])

    def test_real_legacy_ki_mismatch_is_repaired_only_for_diagnostic(self):
        r=inspect('E:/dianji/motor-td3-local-results/ki-warm-response-20261013/trial')
        self.assertEqual(r['raw_timestamp_speed_mismatches'],42)
        self.assertEqual(r['derived_capture_speed_mismatches'],0)
        self.assertEqual(r['windows'],0)

    def test_real_lower_windows_preserve_causal_order(self):
        root='E:/dianji/motor-td3-local-results/lower-commission-20261013/'
        r=inspect(root+'trial',root+'stream')
        self.assertEqual(r['windows'],146)
        self.assertEqual(r['ordering_proven'],146)


if __name__=='__main__': unittest.main()
