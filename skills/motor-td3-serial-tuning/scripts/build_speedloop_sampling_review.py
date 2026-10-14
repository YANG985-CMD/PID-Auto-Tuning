"""Offline v18 collection cadence review to reduce Hall-sector aliasing.

Physical sensor/control signals and CAN layout remain unchanged. Collection
intervals are predetermined, bounded 18.5..21.5ms, approximately 50Hz mean.
"""
import argparse
import json
from pathlib import Path
import build_speedloop_snapshot_review as previous
from build_g431_locked_foc import replace_once

IDENTITY='g431-speedloop-pi-sampling-24s-v18'
BASE_PATCH=previous.patch_port


def interval_us(seq):
    return 18500+(seq*997)%3001


def patch_port(path,motion=False):
    BASE_PATCH(path,motion)
    text=path.read_text(encoding='utf-8')
    text=replace_once(text,'static int motion_begin(void *u,float ref,float kp,float ki) {',
        '''/* Predetermined collection dither: never selected from speed,
 * current, gains or reward. Control/guard tasks keep their original clocks. */
uint32_t motor_td3_g431_diag_interval_us(uint32_t seq) {
    return 18500U+(uint32_t)(((uint64_t)seq*997U)%3001U);
}
static int motion_begin(void *u,float ref,float kp,float ki) {''')
    text=replace_once(text,'if(len>0) diag_due_us=n+DIAG_PERIOD_US;',
        'if(len>0) diag_due_us=n+motor_td3_g431_diag_interval_us(endpoint.telemetry_seq);')
    path.write_text(text,encoding='utf-8',newline='\n')


def build(args):
    saved=previous.IDENTITY,previous.patch_port
    try:
        previous.IDENTITY=IDENTITY;previous.patch_port=patch_port
        result=previous.build(args)
    finally:previous.IDENTITY,previous.patch_port=saved
    result['snapshot_review']['sampling_cadence_changed']=True
    result['sampling_review']=dict(interval_rule='18500+(telemetry_seq*997)%3001 microseconds',
        minimum_interval_us=18500,maximum_interval_us=21500,
        first1200_mean_interval_us=sum(interval_us(i) for i in range(1,1201))/1200,
        sensor_filter_changed=False,control_period_changed=False,guard_period_changed=False,
        telemetry_wire_layout_changed=False,primary_metric_changed=False,
        protection_limits_changed=False,actor_allowed=False,
        deployment_allowed=False,performance_claim_allowed=False)
    (Path(args.output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','arm-bin'):p.add_argument('--'+name,required=True)
    p.add_argument('--compiler',default='gcc');p.add_argument('--temp-root',default='E:/simulink/_codex_tmp')
    build(p.parse_args())
