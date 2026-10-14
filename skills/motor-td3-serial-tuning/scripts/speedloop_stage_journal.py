"""Nonblocking Ki evidence journal. Records actual per-packet stage proofs.

No MATLAB training, inference, device owner, parameter sender or reset. The
motion supervisor stops if this journal fails, stalls or cannot keep up.
"""
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from speedloop_stream_training import StreamObserver, CausalStream
from speedloop_motion_gain_trial import f32

PAIRS = tuple((f32(.003389), f32(ki)) for ki in (.001404, .00144, .001476))


class StageJournal:
    # Use the same reviewed SWD timing snapshot as the native training stream.
    telemetry = StreamObserver.telemetry
    check_progress = StreamObserver.check_progress
    _offer = StreamObserver._offer
    command = StreamObserver.command

    def __init__(self, output):
        self.output = Path(output).resolve()
        if Path('E:/simulink/_codex_tmp').resolve() not in self.output.parents:
            raise ValueError('Use task temporary root')
        self.output.mkdir(parents=True, exist_ok=False)
        self.events = queue.Queue(maxsize=2048)
        self.stop = threading.Event()
        self.error = None
        self.processed = 0
        self.proofs = 0
        self.last_progress = time.perf_counter()
        self.worker = threading.Thread(target=self._run, name='ki-stage-journal', daemon=True)
        self.worker.start()

    def _run(self):
        previous = None
        sent = {}
        try:
            with (self.output / 'events.jsonl').open('w', encoding='utf-8') as log:
                while not self.stop.is_set() or not self.events.empty():
                    try:
                        event = self.events.get(timeout=.02)
                    except queue.Empty:
                        self.last_progress = time.perf_counter()
                        continue
                    if event['kind'] == 'command':
                        c = event['command']
                        if c['type'] == 'gains':
                            if ((c['kp'], c['ki']) not in PAIRS or c['command_seq'] != len(sent) + 1
                                    or event['source'] is None or c['source_t_us'] != event['source']['t_us']):
                                raise ValueError('Unknown or unordered Ki command/source')
                            sent[c['command_seq']] = c
                    else:
                        t = event['packet']
                        if previous and (t['boot_id'] != previous['boot_id'] or t['seq'] != previous['seq'] + 1
                                or not 15000 <= t['t_us'] - previous['t_us'] <= 25000):
                            raise ValueError('Ki journal reset or sequence/time gap')
                        if t['fault']:
                            raise ValueError('Faulted Ki journal')
                        if t['enabled'] and t['elapsed_ms'] >= 3900:
                            if not CausalStream.valid_stage(event['stage_proof'], t):
                                raise ValueError('Ki source/response stage proof missing')
                            c = sent.get(t['applied_seq'])
                            if (c is None or (t['kp'],t['ki']) != (c['kp'],c['ki'])
                                    or not c['source_t_us'] <= t['t_apply_us'] <= c['expires_us']):
                                raise ValueError('Ki actual application missing')
                            self.proofs += 1
                        previous = t
                    log.write(json.dumps(event, allow_nan=False) + '\n')
                    log.flush()
                    self.processed += 1
                    self.last_progress = time.perf_counter()
        except Exception as exc:
            self.error = str(exc)

    def close(self):
        self.stop.set()
        self.worker.join(timeout=2)
        result = dict(closed=not self.worker.is_alive(), error=self.error, processed=self.processed,
            actual_stage_proofs=self.proofs, training_performed=False, hardware_owner=False,
            hardware_writeback=False, actor_auto_activated=False, deployment_allowed=False)
        f = self.output / 'events.jsonl'
        if f.is_file():
            result['event_sha256'] = hashlib.sha256(f.read_bytes()).hexdigest()
        (self.output / 'stage-journal-summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        return result
