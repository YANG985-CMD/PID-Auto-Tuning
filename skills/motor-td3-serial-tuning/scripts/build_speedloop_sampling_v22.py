"""v22 observation-only cadence mixing; v21 control and protections retained."""
import argparse
import json
from pathlib import Path
import build_speedloop_lower16_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-samplingmix-24s-v22'
BASE_PATCH=previous.patch_port

def interval_us(seq):
    x=(seq^0xA5B35705)&0xffffffff
    x=((x^(x>>16))*0x7feb352d)&0xffffffff
    x=((x^(x>>15))*0x846ca68b)&0xffffffff
    x^=x>>16
    return 18500+x%3001

def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'return 18500U+(uint32_t)(((uint64_t)seq*997U)%3001U);',
        '''uint32_t x=seq^0xA5B35705U;
    x=(x^(x>>16))*0x7FEB352DU;
    x=(x^(x>>15))*0x846CA68BU;
    x^=x>>16;
    return 18500U+x%3001U;''')
    path.write_text(text,encoding='utf-8',newline='\n')

def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['sampling_review'].update(interval_rule='stateless-u32-mix-v1',
        first1200_mean_interval_us=sum(interval_us(i) for i in range(1,1201))/1200,
        observation_only=True,previous_modulo_step_alias_diagnosed=True)
    result['sampling_v22_review']=dict(reference_rpm=1000,fixed_kp=.003389,fixed_ki=.00144,
        maximum_motion_seconds=24,host_stop_seconds=23.8,maximum_commands=480,
        sensor_filter_changed=False,control_period_changed=False,
        protection_limits_changed=False,thermal_gate_modified=False,actor_allowed=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','output','arm-bin'):p.add_argument('--'+n,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
