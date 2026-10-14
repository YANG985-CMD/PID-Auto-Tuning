"""Audited v22-v26 real data in a new bidirectional action coordinate; offline."""
import argparse,json
from collections import Counter
from pathlib import Path
from build_speedloop_reference_replay import build_profile
from build_speedloop_fullhall_replay import PROFILES,sha
from speedloop_motion_gain_trial import f32
import speedloop_sampling_v22 as v22
import speedloop_reference_v23 as v23
import speedloop_upper8_reference_v26 as v26
import speedloop_bidirectional_v27 as v27

VERSION='absolute-target-bidirectional16-upper8-scale0p00054224-v7'
REVISION='reference-excited-bidirectional16-upper8-capture-v1'
PROFILE='bidirectional16-upper8-fullhall'
LEVELS=tuple(sorted({f32(v) for v in (.002856927,.002989098,.003121269,.00325344)}|set(v26.LEVELS)))
FIXED=(*PROFILES['upper8-dense-fullhall']['firmwares'],(v22.IDENTITY,v22.IMAGE_SHA))
DYNAMIC=((v23.IDENTITY,v23.IMAGE_SHA,'exogenous-v23-950-1000-1050'),
         (v26.IDENTITY,v26.IMAGE_SHA,v26.REFERENCE_PROFILE),
         (v27.IDENTITY,v27.IMAGE_SHA,v27.REFERENCE_PROFILE))

def build(folders,splits,output,semantic_review,split_review):
    semantic_review,split_review=map(Path,(semantic_review,split_review))
    source=json.loads(semantic_review.read_text());roles=json.loads(split_review.read_text())
    if (not source['passed'] or not source['core_FOC_PI_ADC_Hall_and_protection_source_identical']
        or not source['units_and_control_period_source_identical'] or not roles['passed']
        or roles['assignment_conflicts'] or roles['missing_assignments']):
        raise ValueError('Shared control source and frozen split audit required')
    known={p[:2] for p in (*FIXED,*DYNAMIC)}
    for folder,split in zip(map(Path,folders),splits):
        summary=json.loads((folder/'trial/summary.json').read_text());pair=(summary['firmware_id'],summary['bin_sha256'])
        if pair not in known:raise ValueError('Unknown exact historical firmware')
        if pair==(v27.IDENTITY,v27.IMAGE_SHA):
            proof=Path(source.get('v27_source_delta_file',''))
            if not proof.is_file() or sha(proof)!=source.get('v27_source_delta_sha256'):
                raise ValueError('Exact v26-to-v27 source evidence required')
            delta=json.loads(proof.read_text())
            if (not delta['passed'] or not delta['FOC_PI_ADC_Hall_timing_guard_and_reference_identical']
                or delta['new_sha256']!=v27.IMAGE_SHA):raise ValueError('Unreviewed v27 control delta')
        hall=json.loads((folder/'full-hall-audit/full-hall-edges.json').read_text())
        if roles['roles'].get(hall['boot_id'])!=[split]:raise ValueError('Historical boot role reassignment')
        for line in (folder/'trial/telemetry.jsonl').read_text().splitlines():
            p=json.loads(line)
            if not p['enabled']:continue
            if pair in {r[:2] for r in DYNAMIC}:
                if not v26.reference_matches(p['elapsed_ms'],p['speed_ref']):raise ValueError('Measured reference clock mismatch')
            elif p['speed_ref']!=1000:raise ValueError('Historical fixed reference must be 1000')
    result=build_profile(folders,splits,output,dynamic_identity=v26.IDENTITY,dynamic_sha=v26.IMAGE_SHA,
        dynamic_profile=v26.REFERENCE_PROFILE,fixed_identity=v22.IDENTITY,fixed_sha=v22.IMAGE_SHA,
        fixed_extra=tuple(p for p in FIXED if p!=(v22.IDENTITY,v22.IMAGE_SHA)),
        dynamic_extra=(DYNAMIC[0],DYNAMIC[2]),host_step_limit=.00013556,
        gains=LEVELS,version=VERSION,revision=REVISION,stream_profile=PROFILE)
    coverage=Counter();refs={'train':set(),'validation':set()}
    for item in result['input_manifest']:
        w=json.loads(Path(item['file']).read_text());ref=w['full_hall_reward']['reference_rpm'];refs[item['split']].add(ref)
        coverage[(item['split'],ref,w['state']['kp'],w['action_applied'][0])]+=1
    boots={s:sum(b['split']==s and b['firmware_id'] in (v23.IDENTITY,v26.IDENTITY,v27.IDENTITY) for b in result['whole_boot_split']) for s in refs}
    result.update(actual_reference_source_target_counts=[dict(split=s,reference_rpm=r,source_kp=a,target_kp=b,windows=n)
        for (s,r,a,b),n in sorted(coverage.items())],actual_reference_levels_by_split={s:sorted(v) for s,v in refs.items()},
        dynamic_reference_boots_by_split=boots,dynamic_excitation_present_in_both_splits=all(boots[s]>0 and refs[s]=={950,1000,1050} for s in refs),
        semantic_review_file=str(semantic_review.resolve()),semantic_review_sha256=sha(semantic_review),
        split_review_file=str(split_review.resolve()),split_review_sha256=sha(split_review),
        host_single_kp_step_limit=.00013556,old_large_steps_explicitly_rejected_not_clipped=True,
        current_v26_continuous_negative_runtime_compatible=False,
        new_firmware_negative_continuous_acceptance_review_required=True,training_performed=False)
    (Path(output)/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train',nargs='+',required=True);p.add_argument('--validation',nargs='+',required=True)
    for n in ('output','semantic-review','split-review'):p.add_argument('--'+n,required=True)
    a=p.parse_args();build(a.train+a.validation,['train']*len(a.train)+['validation']*len(a.validation),
        a.output,a.semantic_review,a.split_review)
