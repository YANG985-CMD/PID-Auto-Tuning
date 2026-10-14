"""Synthetic publication, wrap, reset/overwrite and reserved-time failures."""
import struct
import unittest
from unittest.mock import patch
from live_speedloop_hall import LiveHallReader

SYMBOLS=dict(motor_td3_g431_hall_edge_count=1,motor_td3_g431_hall_edges=100)
class Memory:
    def __init__(self,count,after=None):self.counts=iter((count,count if after is None else after));self.reads=[]
    def read32(self,address):return next(self.counts)
    def read_memory_block8(self,address,size):
        self.reads.append((address,size));first=(address-100)//24
        return b''.join(struct.pack('<QIIf4B',1000+(first+i)*5000,16000,5000,1000.,(i%6)+1,6,4,1)
            for i in range(size//24))

class Checks(unittest.TestCase):
    def test_published_records_and_zero_new_rows(self):
        r=LiveHallReader();m=Memory(4);result=r.read(m,SYMBOLS)
        self.assertEqual([p['edge'] for p in result['records']],[1,2,3,4]);self.assertEqual(r.cursor,4)
        self.assertEqual(r.read(Memory(4),SYMBOLS)['records'],[])
    def test_ring_wrap_keeps_ordered_indices(self):
        r=LiveHallReader();r.cursor=830
        class Wrapped(Memory):
            def read_memory_block8(self,address,size):
                self.reads.append((address,size));first=(address-100)//24;start=first if first>=830 else first+832
                return b''.join(struct.pack('<QIIf4B',1000+(start+i)*5000,16000,5000,1000.,1,6,4,1)
                    for i in range(size//24))
        m=Wrapped(835);result=r.read(m,SYMBOLS)
        self.assertEqual([p['edge'] for p in result['records']],list(range(831,836)))
        self.assertEqual([size for address,size in m.reads],[48,72])
    def test_reset_and_backlog_rejected_before_memory_read(self):
        r=LiveHallReader();r.cursor=4
        for count in (3,70):
            m=Memory(count)
            with self.assertRaises(RuntimeError):r.read(m,SYMBOLS)
            self.assertEqual(m.reads,[])
    def test_publication_after_read_cannot_overwrite_old_slots(self):
        r=LiveHallReader()
        with self.assertRaisesRegex(RuntimeError,'overwritten'):r.read(Memory(4,900),SYMBOLS)
    def test_slow_read_trips_before_next_action(self):
        with patch('live_speedloop_hall.time.perf_counter',side_effect=[1,1.007]):
            with self.assertRaisesRegex(RuntimeError,'6ms'):LiveHallReader().read(Memory(0),SYMBOLS)
    def test_unknown_layout_rejected(self):
        with self.assertRaises(ValueError):LiveHallReader(512)

if __name__=='__main__':unittest.main()
