"""Deferred publication, wrap, partial reads and timing failures."""
import unittest
from unittest.mock import patch
from live_speedloop_hall import PipelinedHallReader
from test_live_speedloop_hall import Memory,SYMBOLS


class Checks(unittest.TestCase):
    def test_rows_not_published_until_next_counter_proves_intact(self):
        r=PipelinedHallReader()
        first=r.read(Memory(4),SYMBOLS)
        self.assertEqual(first['records'],[]);self.assertEqual(first['published_count'],0)
        self.assertEqual(first['observed_published_count'],4)
        second=r.read(Memory(8),SYMBOLS)
        self.assertEqual([x['edge'] for x in second['records']],[1,2,3,4])
        self.assertEqual(second['published_count'],4);self.assertEqual(r.read_cursor,8)
        last=r.read(Memory(8),SYMBOLS)
        self.assertEqual([x['edge'] for x in last['records']],[5,6,7,8])

    def test_one_counter_read_per_cycle(self):
        class Counted(Memory):
            def __init__(self):super().__init__(4);self.calls=0
            def read32(self,address):self.calls+=1;return super().read32(address)
        m=Counted();PipelinedHallReader().read(m,SYMBOLS)
        self.assertEqual(m.calls,1)

    def test_counter_reset_backlog_and_deferred_overwrite_fail(self):
        r=PipelinedHallReader();r.read(Memory(4),SYMBOLS)
        for count in (3,70):
            with self.assertRaises(RuntimeError):r.read(Memory(count),SYMBOLS)
        r.pending['start']=-830
        with self.assertRaisesRegex(RuntimeError,'deferred confirmation'):
            r.read(Memory(8),SYMBOLS)
        self.assertEqual(r.cursor,0)

    def test_slow_or_inconsistent_read_cannot_commit(self):
        r=PipelinedHallReader();r.read(Memory(4),SYMBOLS)
        with patch('live_speedloop_hall.time.perf_counter',side_effect=[1,1.007]):
            with self.assertRaisesRegex(RuntimeError,'6ms'):r.read(Memory(8),SYMBOLS)
        self.assertEqual(r.cursor,0);self.assertEqual(r.read_cursor,4)
        class Corrupt(Memory):
            def read_memory_block8(self,address,size):
                blob=bytearray(super().read_memory_block8(address,size));blob[0:8]=(1).to_bytes(8,'little');return blob
        with self.assertRaisesRegex(RuntimeError,'continuous'):r.read(Corrupt(8),SYMBOLS)

    def test_wrap_and_confirmation_preserve_record_order(self):
        class Wrapped(Memory):
            def read_memory_block8(self,address,size):
                first=(address-100)//24
                if first<830:address+=832*24
                return super().read_memory_block8(address,size)
        r=PipelinedHallReader();r.cursor=r.read_cursor=830
        self.assertEqual(r.read(Wrapped(835),SYMBOLS)['records'],[])
        out=r.read(Wrapped(835),SYMBOLS)
        self.assertEqual([x['edge'] for x in out['records']],list(range(831,836)))


if __name__=='__main__':unittest.main()
