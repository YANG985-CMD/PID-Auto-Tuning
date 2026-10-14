"""Exact finite continuous acquisition image, no unreviewed Actor application."""
import argparse
import hashlib
import json
from pathlib import Path
from build_speedloop_continuous import IDENTITY
from speedloop_duration_review import overrides
from speedloop_response_review import validate_action
from speedloop_motion_gain_trial import f32
import speedloop_motion_gain_trial as trial
import speedloop_reactive_probe as reactive

IMAGE_SHA='2a046c1d1c2eb9a838be83e76e3a2471d3a1c4f6f780f9d65908394d4580f43f'
HEX_SHA='9cabe421de97dc5822114a763291e915a0633f3375313cc1921c0d6aa7d7b86c'
IMAGE_BYTES=51092
OLD_SHA='f1e48e4033a7c3fd4cf645b9050c157325ed507580f7f3d60e5b573a0620dd4a'
OLD_BYTES=51084
BASE_CHECK=trial.check_telemetry


def validate(a):
    if not getattr(a,'authorized_continuous',False):raise ValueError('Finite continuous experiment scope required')
    info=json.loads((Path(a.build)/'summary.json').read_text(encoding='utf-8'))
    c=info.get('continuous_review',{})
    if (info['build_id']!=IDENTITY or not info['passed'] or info['bin_sha256']!=IMAGE_SHA
            or info['binary_bytes']!=IMAGE_BYTES or info['hall_trace_capacity']!=832
            or c.get('maximum_motion_seconds')!=24 or c.get('actor_allowed') is not False
            or c.get('fixed_ki')!=.00144 or c.get('thermal_gate_modified') is not False
            or hashlib.sha256((Path(a.build)/'speedloop-pi-review.bin').read_bytes()).hexdigest()!=IMAGE_SHA
            or hashlib.sha256((Path(a.build)/'speedloop-pi-review.hex').read_bytes()).hexdigest()!=HEX_SHA):
        raise ValueError('Only exact reviewed v13 image and finite contract accepted')
    validate_action(a);return info


def expected_reference(ms):
    if ms<4000 or ms>=22000:return 1000
    phase=(ms-4000)%3600
    return 1100 if phase<1200 else 900 if phase<2400 else 1000


def reference_matches(ms,ref):
    return ref in {expected_reference(ms+x) for x in (-2,0,2)}


class ContinuousProbe(reactive.ReactiveProbe):
    def planned(self,ms,ki_probe_sign=0,mode='baseline'):
        if ki_probe_sign or mode not in ('baseline','kp_probe'):raise ValueError('Unsupported action')
        if mode=='baseline' or ms<3900 or ms>=23000:return f32(.003389),f32(.00144)
        # Continue the same causal three-error/250ms decision rule past v12.
        if len(self.history)!=3 or self.history[-1]['elapsed_ms']!=ms:
            raise RuntimeError('Missing causal stream history')
        slot=int((ms-3900)//250)
        if slot<self.slot or (self.slot>=0 and slot>self.slot+1):raise RuntimeError('Decision clock/slot gap')
        if slot>self.slot:
            error=sum(p['error'] for p in self.history)/3
            if error<-20:self.high=True
            elif error>=0:self.high=False
            self.slot=slot;self.decisions.append(dict(slot=slot,elapsed_ms=ms,mean_error_rpm=error,
                source_sequences=[p['seq'] for p in self.history],kp=f32(.00352456 if self.high else .003389),ki=f32(.00144)))
        return f32(.00352456 if self.high else .003389),f32(.00144)


def run(a):
    validate(a)
    if a.phase=='flash':
        import speedloop_motion_v5_flash as flash
        with overrides(flash,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,OLD_SHA=OLD_SHA,OLD_BYTES=OLD_BYTES):
            return flash.flash(a)
    if a.phase=='prepare':
        import speedloop_motion_prepare as prepare
        with overrides(prepare,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA):return prepare.prepare(a)
    if a.phase!='trial':raise ValueError('Unknown phase')
    policy=ContinuousProbe();observer=None
    def check(t,last,sent):
        BASE_CHECK(t,last,sent)
        if t['enabled'] and not reference_matches(t['elapsed_ms'],t['speed_ref']):raise RuntimeError('Actual reference mismatch')
        policy.observe(t)
    if getattr(a,'stream_output',None):
        from speedloop_stream_training import StreamObserver
        from speedloop_stream_training import GAINS
        observer=StreamObserver(a.stream_output,a.trainer_ready_file,getattr(a,'stream_gain_levels',GAINS),
            capture_only=getattr(a,'capture_only',False),hall_capacity=getattr(a,'capture_hall_capacity',None),
            hall_read_profile=getattr(a,'capture_hall_read_profile','immediate-v1'));a.runtime_observer=observer
    try:
        with overrides(trial,IDENTITY=IDENTITY,ENERGIZED_IMAGE_SHA=IMAGE_SHA,STOP_SECONDS=23.8,
            GAIN_CUTOFF_SECONDS=23.7,FINAL_GAIN_SECONDS=23.72,FINAL_GAIN_DEADLINE_SECONDS=23.75,
            MAX_MOTION_SECONDS=24,CAPTURE_SECONDS=26,TIMING_EVIDENCE_SYMBOL='motor_td3_g431_trial_timing',
            HALL_TRACE_CAPACITY=832,planned_gains=policy.planned,check_telemetry=check):
            result=trial.trial(a)
    finally:
        if observer:stream=observer.close()
    result.update(runtime_profile='continuous-24s-real-ack-v1',single_startup=True,
        actor_applied=False,fixed_ki=f32(.00144),deployment_allowed=False,performance_claim_allowed=False,
        probe_decisions=policy.decisions)
    if observer:
        result['stream']=stream
        if stream['error'] or not stream['closed']:result['passed']=False
        ended=dict(physical_trial_passed=result['passed'],stop_acknowledged=result.get('protocol_stop_acknowledged',False),
            core_halted=result.get('core_halted_after_physical_shutdown',False),
            can_released=result.get('can_released_after_shutdown',False),
            final_irq_fault=result.get('final_irq_fault'),final_tx_fault=result.get('final_tx_fault'))
        (Path(a.stream_output)/'session-ended.json').write_text(json.dumps(ended)+'\n',encoding='utf-8')
    (Path(a.output)/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('flash','prepare','trial'))
    for name in ('build','output'):p.add_argument('--'+name,required=True)
    for name in ('nm','pyocd','pack','boot-token-file','stream-output','trainer-ready-file'):p.add_argument('--'+name)
    p.add_argument('--uid',default='0674FF554850715087183841')
    p.add_argument('--gain-mode',choices=('baseline','kp_probe'),default='baseline')
    for name in ('authorized-continuous','energized-update-authorized','power-disconnected-confirmed',
                 'energized-phase-inhibited-confirmed','power-confirmed','authorized-no-thermal-trial'):
        p.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    needed={'flash':('pyocd','pack'),'prepare':('nm',),'trial':('nm','boot_token_file')}
    if any(not getattr(a,n) for n in needed[a.phase]):p.error('Missing phase path')
    if bool(a.stream_output)!=bool(a.trainer_ready_file):p.error('Both stream/trainer paths required')
    raise SystemExit(0 if run(a)['passed'] else 1)
