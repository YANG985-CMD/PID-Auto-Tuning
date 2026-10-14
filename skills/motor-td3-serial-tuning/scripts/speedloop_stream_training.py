"""Nonblocking journal/causal windows for a separate MATLAB training process.

No device owner, parameter sender, reset or Actor activation capability.
All disk I/O and window construction run outside the CAN/STOP thread.
"""
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import queue
import struct
import threading
import time
from speedloop_response_windows import state,temporal_mean
from speedloop_motion_gain_trial import f32

GAINS=(f32(.003389),f32(.00352456))
INTERIOR_GAINS=(f32(.003389),f32(.00345678),f32(.00352456))
LOWER_GAINS=(f32(.00325344),*INTERIOR_GAINS)
LOWER8_GAINS=(f32(.003121269),*LOWER_GAINS)
LOWER16_GAINS=(f32(.002856927),*LOWER8_GAINS)
UPPER8_GAINS=(f32(.003389),f32(.00352456),f32(.00366012))
UPPER8_DENSE_GAINS=tuple(f32(.003389*(1+i/100)) for i in range(9))
BIDIRECTIONAL_V27_GAINS=tuple(map(f32,(.002856927,.002989098,.003121269,.00325344)))+UPPER8_DENSE_GAINS
LOWER31_V28_GAINS=tuple(map(f32,(.002328243,.002460414,.002592585,.002724756)))+BIDIRECTIONAL_V27_GAINS
KI=f32(.00144)


class CausalStream:
    def __init__(self,allowed_gains=GAINS,minimum_response_span_us=60000):
        self.allowed_gains=tuple(allowed_gains)
        if self.allowed_gains not in (GAINS,INTERIOR_GAINS,LOWER_GAINS,LOWER8_GAINS,LOWER16_GAINS,UPPER8_GAINS,UPPER8_DENSE_GAINS,BIDIRECTIONAL_V27_GAINS,LOWER31_V28_GAINS):raise ValueError('Unreviewed gain levels')
        if type(minimum_response_span_us) is not int or minimum_response_span_us not in (60000,200000,300000):
            raise ValueError('Unreviewed response-window span')
        self.minimum_response_span_us=minimum_response_span_us
        self.history=deque(maxlen=3);self.sent={};self.pending=None;self.boot=None
        self.windows=0;self.rejected=0;self.last_command=0

    def command(self,c,source):
        if c['type']!='gains':return
        if (c['kp'] not in self.allowed_gains or c['ki']!=KI or c['command_seq']!=self.last_command+1
                or source is None or c['source_t_us']!=source['t_us']):
            raise ValueError('Unknown or unordered stream action')
        self.last_command=c['command_seq'];self.sent[c['command_seq']]=dict(c)
        if self.pending and self.pending['action']!=[c['kp'],c['ki']]:
            self.rejected+=1;self.pending=None
        if self.pending is None and source['enabled'] and source['elapsed_ms']>=3900:
            if len(self.history)!=3 or self.history[-1]['packet']['t_us']!=source['t_us']:return
            history=[p['packet'] for p in self.history]
            proof=self.history[-1]['stage_proof']
            if not self.valid_stage(proof,source):return
            self.pending=dict(source=source,history=history,source_stage_proof=proof,
                command=c,action=[c['kp'],c['ki']],response=[],response_stage_proofs=[])

    @staticmethod
    def valid_stage(proof,t):
        return (proof is not None and proof['started']==1 and proof['run_seen']==1
                and proof['fault']==0 and proof['irq_fault']==0
                and proof['started_us']<=proof['run_started_us']<=t['t_us']<=proof['last_us']
                and abs((t['t_us']-proof['started_us'])/1000-t['elapsed_ms'])<=2)

    def telemetry(self,t,proof):
        if self.boot is None:self.boot=t['boot_id']
        if self.boot!=t['boot_id'] or t['fault']:raise ValueError('Reset/fault in stream')
        if self.history:
            p=self.history[-1]['packet']
            if t['seq']!=p['seq']+1 or not 15000<=t['t_us']-p['t_us']<=25000:
                raise ValueError('Stream sequence/time gap')
        if not all(math.isfinite(v) for v in state(t)):raise ValueError('Nonfinite state')
        if t['enabled'] and (abs(t['speed'])>=1800 or t['current']>=2 or not 18<=t['vbus']<=30):
            raise ValueError('Stream physical boundary')
        self.history.append(dict(packet=t,stage_proof=proof))
        if not t['enabled']:
            if self.pending:self.rejected+=1;self.pending=None
            return None
        if not self.pending:return None
        p=self.pending;c=self.sent.get(t['applied_seq'])
        if t['applied_seq']<p['command']['command_seq']:return None
        if (c is None or [t['kp'],t['ki']]!=[c['kp'],c['ki']]
                or not c['source_t_us']<=t['t_apply_us']<=c['expires_us']):
            raise ValueError('Missing actual command/apply readback')
        if [t['kp'],t['ki']]!=p['action']:raise ValueError('Response crosses gain change')
        if not self.valid_stage(proof,t):raise ValueError('Actual RunStage timing proof missing')
        holding=state(p['source'])[7:9]==p['action']
        effective=p['source']['t_us'] if holding else t['t_apply_us']
        if not holding:
            p.setdefault('first_apply_us',t['t_apply_us']);effective=p['first_apply_us']
        if t['t_us']<=effective:return None
        p['response'].append(t);p['response_stage_proofs'].append(proof)
        response=p['response']
        if len(response)<4 or response[-1]['t_us']-response[0]['t_us']<self.minimum_response_span_us:return None
        self.pending=None;self.windows+=1
        times=[r['t_us'] for r in response]
        mse=temporal_mean([(r['speed_ref']-r['speed'])**2 for r in response],times)
        current=max(r['current'] for r in response);speed=max(abs(r['speed']) for r in response)
        saturation=temporal_mean([float(r['current']>=1.98) for r in response],times)
        delta=(p['action'][0]-p['source']['kp'])/.00027112
        reward=-mse/1e6-.12*(current/2)**2-.08*max(0,(speed-1500)/300)**2-.1*saturation-.005*delta**2
        ids=sorted({r['applied_seq'] for r in response}|{p['command']['command_seq']})
        return dict(schema_version=1,source='real_motor_live_actual_ack',boot_id=self.boot,
            window_index=self.windows,state=p['source'],state_history=p['history'],
            source_stage_proof=p['source_stage_proof'],response=response,
            response_stage_proofs=p['response_stage_proofs'],commands=[self.sent[i] for i in ids],
            first_command_seq=p['command']['command_seq'],t_effective_us=effective,
            action_applied=p['action'],physical_delta_action=[delta,0],reward=reward,
            terminated=False,truncated=False,session_shutdown_pending=True,
            action_mapping_redefinition_required=self.allowed_gains in (LOWER16_GAINS,UPPER8_GAINS,UPPER8_DENSE_GAINS,BIDIRECTIONAL_V27_GAINS,LOWER31_V28_GAINS),
            deployment_allowed=False,performance_claim_allowed=False,actor_applied=False)


class StreamObserver:
    def __init__(self,output,ready_file,allowed_gains=GAINS,*,capture_only=False,hall_capacity=None,hall_read_profile='immediate-v1'):
        self.allowed_gains=tuple(allowed_gains)
        if self.allowed_gains not in (GAINS,INTERIOR_GAINS,LOWER_GAINS,LOWER8_GAINS,LOWER16_GAINS,UPPER8_GAINS,UPPER8_DENSE_GAINS,BIDIRECTIONAL_V27_GAINS,LOWER31_V28_GAINS):raise ValueError('Unreviewed stream gain levels')
        if self.allowed_gains in (LOWER16_GAINS,UPPER8_GAINS,UPPER8_DENSE_GAINS,BIDIRECTIONAL_V27_GAINS,LOWER31_V28_GAINS) and not capture_only:
            raise ValueError('New exploration point requires a new action mapping; capture-only until reviewed')
        self.hall_reader=None
        if hall_capacity is not None:
            if not capture_only:raise ValueError('Live Hall extension is capture-only until audited')
            from live_speedloop_hall import LiveHallReader,PipelinedHallReader,BoundedPipelinedHallReader
            if hall_read_profile not in ('immediate-v1','pipelined-v1','pipelined-chunk8-v2'):
                raise ValueError('Unknown Hall read profile')
            reader={'immediate-v1':LiveHallReader,'pipelined-v1':PipelinedHallReader,
                    'pipelined-chunk8-v2':BoundedPipelinedHallReader}[hall_read_profile]
            self.hall_reader=reader(hall_capacity)
        self.hall_read_profile=hall_read_profile
        self.output=Path(output).resolve();self.capture_only=bool(capture_only)
        self.ready_file=None if ready_file is None else Path(ready_file)
        if Path('E:/simulink/_codex_tmp').resolve() not in self.output.parents:
            raise ValueError('Use task temporary root')
        if self.capture_only:
            if self.ready_file is not None:raise ValueError('Capture-only mode cannot claim a live MATLAB trainer')
        else:
            if self.ready_file is None or not self.ready_file.is_file():raise ValueError('MATLAB worker not ready before motion')
            ready=json.loads(self.ready_file.read_text(encoding='utf-8'))
            if self.allowed_gains==INTERIOR_GAINS and ready.get('stream_gain_profile')!='interior3':
                raise ValueError('MATLAB is not configured for reviewed midpoint commissioning')
            if self.allowed_gains==LOWER_GAINS and ready.get('stream_gain_profile')!='lower4':
                raise ValueError('MATLAB is not configured for separately approved lower commissioning')
            if self.allowed_gains==LOWER8_GAINS and ready.get('stream_gain_profile')!='lower8':
                raise ValueError('MATLAB is not configured for extended negative support')
            if (ready.get('training_process_separate_from_CAN') is not True or ready.get('deployment_allowed') is not False
                    or ready.get('actor_auto_activated') is not False or ready.get('action_mask')!=[1,0]):
                raise ValueError('Unreviewed training worker')
        self.output.mkdir(parents=True,exist_ok=False)
        self.events=queue.Queue(maxsize=2048);self.stop=threading.Event()
        self.error=None;self.processed=0;self.windows=0;self.last_progress=time.perf_counter()
        self.worker=threading.Thread(target=self._run,name='motor-stream-journal',daemon=True)
        self.worker.start()

    def _offer(self,item):
        if self.error:raise RuntimeError('Stream journal failed: '+self.error)
        try:self.events.put_nowait(item)
        except queue.Full:raise RuntimeError('Stream backpressure; stop rather than drop causal data')

    def command(self,c,source):self._offer(dict(kind='command',command=c,source=source))

    def telemetry(self,t,target,symbols):
        proof=None
        if t['enabled'] and t['elapsed_ms']>=3900:
            # Immutable begin/run timestamps and a current latched timing fault.
            values=struct.unpack('<QQQIII',bytes(target.read_memory_block8(symbols['motor_td3_g431_trial_timing'],36)))
            proof=dict(zip(('started_us','run_started_us','last_us','started','run_seen','fault'),values))
            proof['irq_fault']=target.read32(symbols['irq_fault'])
        event=dict(kind='telemetry',packet=dict(t),stage_proof=proof)
        if self.hall_reader:event['hall_capture']=self.hall_reader.read(target,symbols)
        self._offer(event)

    def check_progress(self,now):
        if self.error:raise RuntimeError('Stream journal failed: '+self.error)
        if now-self.last_progress>1:raise RuntimeError('Stream journal stalled')

    def _run(self):
        stream=CausalStream(self.allowed_gains)
        try:
            with (self.output/'events.jsonl').open('w',encoding='utf-8') as log:
                while not self.stop.is_set() or not self.events.empty():
                    if not self.capture_only:
                        progress=self.ready_file.with_name('progress.json')
                        if self.ready_file.with_name('failure.json').exists():raise RuntimeError('MATLAB trainer rejected a window')
                        try: stamp=progress.stat().st_mtime
                        except FileNotFoundError:
                            # Atomic replacement gap is not a lost lease.
                            stamp=getattr(self,'trainer_stamp',self.ready_file.stat().st_mtime)
                        self.trainer_stamp=stamp
                        if time.time()-stamp>10:raise RuntimeError('MATLAB trainer progress lease expired')
                    try:item=self.events.get(timeout=.02)
                    except queue.Empty:self.last_progress=time.perf_counter();continue
                    log.write(json.dumps(item,allow_nan=False)+'\n');log.flush()
                    row=None
                    if item['kind']=='command':stream.command(item['command'],item['source'])
                    else:row=stream.telemetry(item['packet'],item['stage_proof'])
                    if row:
                        blob=(json.dumps(row,allow_nan=False)+'\n').encode('utf-8')
                        name=f'window-{stream.windows:05d}'
                        staging=self.output/(name+'.part');staging.write_bytes(blob)
                        staging.replace(self.output/(name+'.json'))
                        self.windows=stream.windows
                    self.processed+=1;self.last_progress=time.perf_counter()
            self.rejected=stream.rejected
        except Exception as exc:self.error=str(exc)

    def close(self):
        self.stop.set();self.worker.join(timeout=2)
        result=dict(closed=not self.worker.is_alive(),error=self.error,processed=self.processed,
            committed_windows=self.windows,hardware_owner=False,hardware_writeback=False,
            capture_only=self.capture_only,training_performed_by_observer=False)
        if (self.output/'events.jsonl').exists():
            result['event_sha256']=hashlib.sha256((self.output/'events.jsonl').read_bytes()).hexdigest()
        if self.hall_reader:
            result['hall_read_profile']=self.hall_read_profile
            result['live_hall_count']=self.hall_reader.cursor
            result['maximum_live_hall_read_ms']=max(self.hall_reader.read_ms,default=0)
            if hasattr(self.hall_reader,'last_failure'):result['Hall_read_failure_details']=self.hall_reader.last_failure
        (self.output/'stream-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        return result
