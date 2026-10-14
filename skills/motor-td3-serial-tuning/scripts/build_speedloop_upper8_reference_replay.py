"""Exact v24/v25/v26 upper Kp data; validate measured reference independently."""
import argparse
from collections import Counter
import json
from pathlib import Path
from build_speedloop_reference_replay import build_profile
from build_speedloop_fullhall_replay import PROFILES
import speedloop_upper8_continuous as old
import speedloop_upper8_reference_v26 as new

VERSION='absolute-target-upper8-dense-reference-scale0p00054224-v6'
REVISION='reference-excited-upper8-dense-capture-v1'
FIXED_IDENTITIES=PROFILES['upper8-dense-fullhall']['firmwares']

def validate_source_identity(identity,image_sha):
    if (identity,image_sha) not in (*FIXED_IDENTITIES,(new.IDENTITY,new.IMAGE_SHA)):
        raise ValueError('Unknown exact source firmware identity/hash')

def validate_reference_packet(identity,packet):
    if not packet['enabled']:return
    if identity==new.IDENTITY:
        if not new.reference_matches(packet['elapsed_ms'],packet['speed_ref']):
            raise ValueError('Actual reference disagrees with exact v26 clock')
    elif identity in {p[0] for p in FIXED_IDENTITIES}:
        if packet['speed_ref']!=1000:raise ValueError('Actual fixed firmware reference must be 1000')
    else:raise ValueError('Unknown source firmware identity')

def build(folders,splits,output):
    for folder in map(Path,folders):
        summary=json.loads((folder/'trial/summary.json').read_text());identity=summary['firmware_id']
        validate_source_identity(identity,summary['bin_sha256'])
        for line in (folder/'trial/telemetry.jsonl').read_text().splitlines():
            validate_reference_packet(identity,json.loads(line))
    result=build_profile(folders,splits,output,dynamic_identity=new.IDENTITY,dynamic_sha=new.IMAGE_SHA,
        fixed_identity=old.IDENTITY,fixed_sha=old.IMAGE_SHA,dynamic_profile=new.REFERENCE_PROFILE,
        gains=new.LEVELS,version=VERSION,revision=REVISION,stream_profile='upper8-dense-fullhall',
        fixed_extra=tuple(p for p in FIXED_IDENTITIES if p!=(old.IDENTITY,old.IMAGE_SHA)))
    coverage=Counter();refs={'train':set(),'validation':set()}
    for item in result['input_manifest']:
        w=json.loads(Path(item['file']).read_text());ref=w['full_hall_reward']['reference_rpm']
        refs[item['split']].add(ref)
        coverage[(item['split'],ref,w['state']['kp'],w['action_applied'][0])]+=1
    boots={split:sum(b['split']==split and b['firmware_id']==new.IDENTITY for b in result['whole_boot_split']) for split in refs}
    result.update(actual_reference_source_target_counts=[dict(split=s,reference_rpm=r,source_kp=a,target_kp=b,windows=n)
        for (s,r,a,b),n in sorted(coverage.items())],actual_reference_levels_by_split={s:sorted(v) for s,v in refs.items()},
        dynamic_reference_boots_by_split=boots,
        dynamic_excitation_present_in_both_splits=all(boots[s]>0 and refs[s]=={950,1000,1050} for s in refs),
        fixed_reference_rows_alone_are_not_dynamic_excitation_evidence=True)
    (Path(output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train',nargs='+',required=True);p.add_argument('--validation',nargs='+',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();build(a.train+a.validation,['train']*len(a.train)+['validation']*len(a.validation),a.output)
