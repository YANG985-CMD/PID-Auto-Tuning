"""Frozen host Actor mirror; advisory-only until separate physical evaluation.

Preserves MATLAB normalization, input/output masks, absolute action mapping.
Nearest approved-level mapping is explicit policy behavior, not a raw Actor
output or a claim of physical performance. No hardware libraries or commands.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np


class FixedActor:
    def __init__(self,networks,expected_checkpoint):
        self.path=Path(networks);self.sha256=hashlib.sha256(self.path.read_bytes()).hexdigest()
        data=json.loads(self.path.read_text(encoding='utf-8'));self.contract=data['learning_contract']
        if (data['source_checkpoint_sha256']!=expected_checkpoint or data['deployment_allowed'] is not False
                or data['generated_mcu_code'] is not False or data['action_mask']!=[1,0]):
            raise ValueError('Unreviewed checkpoint, code capability or Ki mask')
        c=self.contract
        if c['observation_profile']!='history20-40' or c['action_coordinates']!='absolute-target':
            raise ValueError('Unknown input/action transform')
        self.center=np.array(c['state_center'],dtype=np.float64)
        self.scale=np.array(c['state_scale'],dtype=np.float64)
        self.input_mask=np.array(c['actor_input_mask'],dtype=np.float32)
        self.output_scale=np.array(c['actor_output_affine_scale'],dtype=np.float32)
        self.output_bias=np.array(c['actor_output_affine_bias'],dtype=np.float32)
        self.output_mask=np.array(c['action_mask'],dtype=np.float32)
        self.action_lower=float(c.get('action_lower_limit',[0,-1])[0])
        self.action_upper=float(c.get('action_upper_limit',[.5,1])[0])
        self.levels=np.array([0,.25,.5],dtype=np.float64)
        if c.get('stream_gain_profile')=='lower4':
            if (c.get('lower_commission_learning_initialized') is not True
                    or c.get('action_lower_limit')!=[-.5,-1] or c.get('action_upper_limit')!=[.5,1]
                    or not np.array_equal(self.output_scale,[.5,1]) or not np.array_equal(self.output_bias,[0,0])):
                raise ValueError('Inconsistent experimental negative action contract')
            self.levels=np.array([-.5,0,.25,.5],dtype=np.float64)
        elif c.get('stream_gain_profile')=='lower8':
            if (c.get('lower8_learning_initialized') is not True
                    or c.get('action_lower_limit')!=[-1,-1] or c.get('action_upper_limit')!=[.5,1]
                    or not np.array_equal(self.output_scale,[.75,1]) or not np.array_equal(self.output_bias,[-.25,0])):
                raise ValueError('Inconsistent extended negative action contract')
            lower=(float(np.float32(.003121269))-float(np.float32(.003389)))/.00027112
            self.levels=np.array([lower,-.5,0,.25,.5],dtype=np.float64)
        elif c.get('stream_gain_profile')=='lower8-sampling':
            if (c.get('older_fixed_cadence_replay_excluded') is not True
                    or c.get('action_lower_limit')!=[-1,-1] or c.get('action_upper_limit')!=[0,1]
                    or not np.array_equal(self.output_scale,[.5,1]) or not np.array_equal(self.output_bias,[-.5,0])):
                raise ValueError('Inconsistent fresh-sampling action contract')
            lower=(float(np.float32(.003121269))-float(np.float32(.003389)))/.00027112
            self.levels=np.array([lower,-.5,0],dtype=np.float64)
        if (self.center.shape!=(10,) or self.scale.shape!=(10,) or np.any(self.scale<=0)
                or not np.all(np.isfinite(self.center)) or not np.all(np.isfinite(self.scale))
                or self.input_mask.shape!=(10,) or not np.all(np.isin(self.input_mask,[0,1]))
                or not np.array_equal(self.output_mask,[1,0])):
            raise ValueError('Malformed explicit transform')
        weights={(v['layer'],v['parameter']):np.array(v['value'],dtype=np.float32).reshape(tuple(v['shape']))
                 for v in data['actor']}
        if set(weights)!={(f'fc{i}',p) for i in range(1,4) for p in ('Weights','Bias')}:
            raise ValueError('Unsupported Actor learnables')
        self.layers=[]
        for i,shape in enumerate(((16,10),(16,16),(2,16)),1):
            w=weights[(f'fc{i}','Weights')];b=weights[(f'fc{i}','Bias')].ravel()
            if w.shape!=shape or b.shape!=(shape[0],) or not np.all(np.isfinite(w)) or not np.all(np.isfinite(b)):
                raise ValueError('Wrong layer shape or nonfinite weights')
            self.layers.append((w,b))

    def observation(self,history):
        if len(history)!=3:raise ValueError('Need three actual telemetry packets')
        if len({t['boot_id'] for t in history})!=1 or not all(t['enabled'] and t['fault']==0 for t in history):
            raise ValueError('History crosses reset, disabled state or fault')
        if any(b['seq']!=a['seq']+1 or not 15000<=b['t_us']-a['t_us']<=25000 for a,b in zip(history,history[1:])):
            raise ValueError('Noncausal or missing history')
        t=history[-1]
        values=[t['speed_ref'],t['speed'],t['speed_ref']-t['speed'],t['error_history'],t['integral_output'],
                t['current'],t['vbus'],t['kp'],t['ki'],t['elapsed_ms']]
        x=np.array(values,dtype=np.float64)/np.array([1000,1000,1000,1000,3,2,24,.003389,.00144,3000])
        x[3]=(history[-2]['speed_ref']-history[-2]['speed'])/1000
        x[8]=(history[-3]['speed_ref']-history[-3]['speed'])/1000
        x=np.clip(x,-5,5).astype(np.float32).astype(np.float64)
        result=np.clip((x-self.center)/self.scale,-5,5).astype(np.float32)
        if not np.all(np.isfinite(result)):raise ValueError('Nonfinite normalized state')
        return result

    def predict(self,history):
        x=self.observation(history)*self.input_mask
        for i,(w,b) in enumerate(self.layers):
            x=(w@x+b).astype(np.float32)
            x=np.maximum(x,0) if i<2 else np.tanh(x)
        action=(x*self.output_scale+self.output_bias)*self.output_mask
        if (not np.all(np.isfinite(action)) or not self.action_lower-.000001<=action[0]<=self.action_upper+.000001 or action[1]!=0):
            raise ValueError('Actor left declared experimental support or Ki mask')
        # Ties choose the lower approved action, matching MATLAB min().
        level=int(np.argmin(np.abs(np.float64(action[0])-self.levels)))
        mapped=float(self.levels[level]);kp=float(np.float32(.003389+mapped*.00027112));ki=float(np.float32(.00144))
        return dict(raw_action=action.astype(float).tolist(),projected_absolute_action=[mapped,0],
            kp=kp,ki=ki,level=level,source_seq=history[-1]['seq'],source_t_us=history[-1]['t_us'],
            hardware_writeback=False)


def verify(folder,output):
    folder=Path(folder);summary=json.loads((folder/'policy-reference-summary.json').read_text(encoding='utf-8'))
    actor=FixedActor(folder/'networks.json',summary['checkpoint_sha256'])
    refs=json.loads((folder/'references.json').read_text(encoding='utf-8'))
    errors=[];latencies=[];levels=[];obs_errors=[]
    for r in refs:
        begin=time.perf_counter();p=actor.predict(r['history']);latencies.append((time.perf_counter()-begin)*1000)
        errors.append(max(abs(a-b) for a,b in zip(p['raw_action'],r['raw_action'])))
        obs_errors.append(float(np.max(np.abs(actor.observation(r['history'])-np.array(r['observation'])))))
        if (p['projected_absolute_action']!=r['projected_absolute_action'] or p['kp']!=r['projected_kp']
                or p['ki']!=r['projected_ki']):raise ValueError('Projection or gain mapping differs from MATLAB')
        levels.append(p['level'])
    if max(errors)>1e-6 or max(obs_errors)>1e-7:raise ValueError('Host inference does not match MATLAB')
    result=dict(passed=True,hardware_accessed=False,hardware_writeback=False,reference_vectors=len(refs),
        checkpoint_sha256=summary['checkpoint_sha256'],networks_sha256=actor.sha256,
        maximum_action_abs_error=max(errors),maximum_observation_abs_error=max(obs_errors),
        projection_and_gains_match_matlab=True,
        experimental_projection_levels=actor.levels.tolist(),
        projected_level_counts={str(float(v)):levels.count(g) for g,v in enumerate(actor.levels)},
        maximum_inference_ms=max(latencies),mean_inference_ms=sum(latencies)/len(latencies),
        physical_actor_benchmark_performed=False,projection_is_part_of_policy=True,
        deployment_allowed=False,performance_claim_allowed=False)
    output=Path(output)
    if Path('E:/simulink/_codex_tmp').resolve() not in output.resolve().parents:raise ValueError('Use task temporary root')
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();verify(a.folder,a.output)
