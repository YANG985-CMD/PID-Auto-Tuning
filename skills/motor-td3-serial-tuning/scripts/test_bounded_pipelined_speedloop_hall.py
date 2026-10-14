import gc
import unittest
from unittest.mock import patch
from live_speedloop_hall import BoundedPipelinedHallReader
from test_live_speedloop_hall import Memory,SYMBOLS

class Checks(unittest.TestCase):
    def test_single_block_and_backlog_drains_without_dropped_edges(self):
        class Counted(Memory):
            def __init__(self):super().__init__(30);self.blocks=[]
            def read32(self,address):return 30
            def read_memory_block8(self,address,size):
                self.blocks.append(size);return super().read_memory_block8(address,size)
        memory=Counted();r=BoundedPipelinedHallReader();edges=[]
        for expected in (8,16,24,30,30):
            result=r.read(memory,SYMBOLS);self.assertEqual(result['read_end_cursor'],expected)
            edges.extend(x['edge'] for x in result['records'])
        self.assertEqual(edges,list(range(1,31)))
        self.assertEqual(memory.blocks,[192,192,192,144])
    def test_wrap_uses_only_one_block_per_cycle(self):
        class Wrapped(Memory):
            def read_memory_block8(self,address,size):
                if (address-100)//24<830:address+=832*24
                return super().read_memory_block8(address,size)
        r=BoundedPipelinedHallReader();r.cursor=r.read_cursor=830
        self.assertEqual(r.read(Wrapped(840),SYMBOLS)['read_end_cursor'],832)
        second=r.read(Wrapped(840),SYMBOLS);self.assertEqual(second['read_end_cursor'],840)
        self.assertEqual([x['edge'] for x in second['records']],[831,832])
    def test_timeout_records_details_but_cannot_commit(self):
        r=BoundedPipelinedHallReader();r.read(Memory(4),SYMBOLS)
        collecting=gc.isenabled()
        with patch('live_speedloop_hall.time.perf_counter',side_effect=[1,1.001,1.006,1.007]):
            with self.assertRaisesRegex(RuntimeError,'6ms'):r.read(Memory(8),SYMBOLS)
        self.assertEqual(r.read_cursor,4);self.assertEqual(r.cursor,0)
        self.assertEqual(r.last_failure['block_records'],4)
        self.assertAlmostEqual(r.last_failure['read_ms'],7)
        self.assertEqual(gc.isenabled(),collecting)
    def test_gc_restoration_on_corrupt_read(self):
        r=BoundedPipelinedHallReader();r.read(Memory(4),SYMBOLS)
        collecting=gc.isenabled()
        with self.assertRaises(RuntimeError):r.read(Memory(3),SYMBOLS)
        self.assertEqual(gc.isenabled(),collecting)
    def test_backlog_and_deferred_overwrite_still_fail(self):
        r=BoundedPipelinedHallReader();r.read(Memory(4),SYMBOLS)
        with self.assertRaises(RuntimeError):r.read(Memory(70),SYMBOLS)
        r.pending['start']=-830
        with self.assertRaisesRegex(RuntimeError,'deferred confirmation'):r.read(Memory(8),SYMBOLS)

if __name__=='__main__':unittest.main()
