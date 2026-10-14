"""Read published Hall ring records from the existing telemetry owner.

Read-only, no extra debug session, reset, halt, device writes or parameters.
Bound the work and reject overwrite. Firmware publishes a record before count.
"""
import struct
import time
import gc

class LiveHallReader:
    def __init__(self,capacity=832):
        if capacity!=832:raise ValueError('Only reviewed ring layout accepted')
        self.capacity=capacity;self.cursor=0;self.last_time=None;self.read_ms=[]
    def read(self,target,symbols):
        started=time.perf_counter();count=target.read32(symbols['motor_td3_g431_hall_edge_count'])
        if count<self.cursor or count-self.cursor>64:raise RuntimeError('Hall ring reset or capture backlog')
        rows=[];index=self.cursor
        while index<count:
            n=min(count-index,self.capacity-index%self.capacity)
            blob=bytes(target.read_memory_block8(symbols['motor_td3_g431_hall_edges']+(index%self.capacity)*24,n*24))
            for offset in range(n):
                timestamp,ticks,period,rpm,code,previous,stage,valid=struct.unpack_from('<QIIf4B',blob,offset*24)
                if self.last_time is not None and timestamp<=self.last_time:raise RuntimeError('Hall clock not increasing')
                rows.append(dict(edge=index+offset+1,t_us=timestamp,raw_timer_ticks=ticks,period_us=period,
                    rpm=rpm,hall_code=code,previous_code=previous,model_stage=stage,valid=bool(valid)))
                self.last_time=timestamp
            index+=n
        after=target.read32(symbols['motor_td3_g431_hall_edge_count'])
        if after<count or after-self.cursor>self.capacity:raise RuntimeError('Hall ring overwritten during read')
        duration=(time.perf_counter()-started)*1000;self.read_ms.append(duration)
        if duration>6:raise RuntimeError('Hall read exceeded reserved 6ms budget')
        self.cursor=count
        return dict(published_count=count,records=rows,read_ms=duration)


class PipelinedHallReader(LiveHallReader):
    """Confirm the prior read with this packet's counter before publishing it.

    This removes one SWD round trip, not the overwrite proof. Last unconfirmed
    rows are recovered only from the immutable halted tail during final audit.
    All I/O stays with the existing supervisor, and the 6ms budget remains.
    """
    def __init__(self,capacity=832):
        super().__init__(capacity)
        self.read_cursor=0
        self.pending=None

    def read(self,target,symbols):
        started=time.perf_counter()
        count=target.read32(symbols['motor_td3_g431_hall_edge_count'])
        if count<self.read_cursor or count-self.read_cursor>64:
            raise RuntimeError('Hall ring reset or capture backlog')
        rows=[];confirmed_count=self.cursor
        if self.pending is not None:
            if count-self.pending['start']>self.capacity:
                raise RuntimeError('Hall ring overwritten before deferred confirmation')
            rows=self.pending['rows'];confirmed_count=self.pending['end']
        new_rows=[];index=self.read_cursor;last_time=self.last_time
        while index<count:
            n=min(count-index,self.capacity-index%self.capacity)
            blob=bytes(target.read_memory_block8(
                symbols['motor_td3_g431_hall_edges']+(index%self.capacity)*24,n*24))
            for offset in range(n):
                timestamp,ticks,period,rpm,code,previous,stage,valid=struct.unpack_from('<QIIf4B',blob,offset*24)
                if last_time is not None and (timestamp<=last_time or timestamp-last_time!=period):
                    raise RuntimeError('Hall clock or period not continuous')
                new_rows.append(dict(edge=index+offset+1,t_us=timestamp,raw_timer_ticks=ticks,
                    period_us=period,rpm=rpm,hall_code=code,previous_code=previous,
                    model_stage=stage,valid=bool(valid)))
                last_time=timestamp
            index+=n
        duration=(time.perf_counter()-started)*1000;self.read_ms.append(duration)
        if duration>6:
            raise RuntimeError('Hall read exceeded reserved 6ms budget')
        self.pending=dict(start=self.read_cursor,end=count,rows=new_rows)
        self.read_cursor=count;self.cursor=confirmed_count;self.last_time=last_time
        return dict(published_count=confirmed_count,records=rows,read_ms=duration,
                    observed_published_count=count,confirmation='next-counter-before-commit-v1')


class BoundedPipelinedHallReader(PipelinedHallReader):
    """One contiguous block of at most eight records per cycle.

    Backlog and next-counter overwrite checks are retained. Wrap is drained on
    the following cycle. GC is restored after this bounded read; OS/USB delays
    still trip the same 6ms limit. This does not provide hard real-time I/O.
    """
    def read(self,target,symbols):
        collecting=gc.isenabled()
        if collecting:gc.disable()
        try:return self._bounded_read(target,symbols)
        finally:
            if collecting:gc.enable()

    def _bounded_read(self,target,symbols):
        started=time.perf_counter()
        count=target.read32(symbols['motor_td3_g431_hall_edge_count'])
        counter_done=time.perf_counter()
        if count<self.read_cursor or count-self.read_cursor>64:
            raise RuntimeError('Hall ring reset or capture backlog')
        rows=[];confirmed_count=self.cursor
        if self.pending is not None:
            if count-self.pending['start']>self.capacity:
                raise RuntimeError('Hall ring overwritten before deferred confirmation')
            rows=self.pending['rows'];confirmed_count=self.pending['end']
        index=self.read_cursor
        n=min(8,count-index,self.capacity-index%self.capacity)
        blob=bytes(target.read_memory_block8(
            symbols['motor_td3_g431_hall_edges']+(index%self.capacity)*24,n*24)) if n else b''
        io_done=time.perf_counter()
        new_rows=[];last_time=self.last_time
        for offset in range(n):
            timestamp,ticks,period,rpm,code,previous,stage,valid=struct.unpack_from('<QIIf4B',blob,offset*24)
            if last_time is not None and (timestamp<=last_time or timestamp-last_time!=period):
                raise RuntimeError('Hall clock or period not continuous')
            new_rows.append(dict(edge=index+offset+1,t_us=timestamp,raw_timer_ticks=ticks,
                period_us=period,rpm=rpm,hall_code=code,previous_code=previous,
                model_stage=stage,valid=bool(valid)))
            last_time=timestamp
        duration=(time.perf_counter()-started)*1000;self.read_ms.append(duration)
        details=dict(read_ms=duration,counter_ms=(counter_done-started)*1000,
            block_io_ms=(io_done-counter_done)*1000,decode_ms=duration-(io_done-started)*1000,
            observed_count=count,read_start_cursor=index,read_end_cursor=index+n,
            block_records=n,remaining_backlog=count-index-n,GC_disabled_during_read=True)
        self.last_read_details=details
        if duration>6:
            self.last_failure=details
            raise RuntimeError('Hall read exceeded reserved 6ms budget')
        self.pending=dict(start=index,end=index+n,rows=new_rows)
        self.read_cursor=index+n;self.cursor=confirmed_count;self.last_time=last_time
        return dict(published_count=confirmed_count,records=rows,read_ms=duration,
            observed_published_count=count,confirmation='next-counter-before-commit-v1',
            read_start_cursor=index,read_end_cursor=index+n,read_details=details)
