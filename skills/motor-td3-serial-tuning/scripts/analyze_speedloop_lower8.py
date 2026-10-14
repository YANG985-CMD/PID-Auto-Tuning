"""Actual lower8 gain/readback/response audit. No predicted plant results."""
import argparse
import json
from pathlib import Path
import analyze_speedloop_segments as previous
from speedloop_duration_review import overrides
from speedloop_lower8_response import IDENTITY,IMAGE_SHA,KP_LEVELS,PATTERN,SEED


def run(trial,contract,output):
    with overrides(previous,IDENTITY=IDENTITY,IMAGE_SHA=IMAGE_SHA,
                   INTERIOR_GAINS=KP_LEVELS,PATTERN=PATTERN,SEED=SEED):
        result=previous.run(trial,contract,output)
    result.update(exact_kp_levels=list(KP_LEVELS),fixed_ki=.00144,
        source='real_motor_lower8_prepositioned_segment_responses',
        level_definitions={'0':'baseline','1':'Kp -4%','2':'Kp -7.9%'},
        statistical_note='15 gain-assigned segments in one physical boot; no independent Actor repeat',
        statistical_significance_test_performed=False)
    (Path(output)/'gain-effect-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trial','contract','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.trial,a.contract,a.output)
