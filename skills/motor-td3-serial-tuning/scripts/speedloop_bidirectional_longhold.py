"""Finite v27 long-hold data, for distinct 300ms replay qualification."""
import speedloop_bidirectional_v27 as base
from speedloop_bidirectional_v27 import IDENTITY,IMAGE_SHA,HEX_SHA,IMAGE_BYTES,PRIOR_SHA,PRIOR_BYTES,LEVELS,KI,BASE_INDEX,ReferenceProbe,reference_matches,reference_rpm,HALL_READ_PROFILE,sha,read
from speedloop_duration_review import overrides
PLATEAU_START_MS=base.PLATEAU_START_MS;PLATEAU_END_MS=base.PLATEAU_END_MS;PLATEAU_MS=base.PLATEAU_MS
PATTERNS_BY_BATCH=(
    ((4,3,2,2,2,2,2,2)+tuple([1]*20)+(2,3,4,4),
     (4,3,2,2,2,2,2,2)+tuple([1]*20)+(2,3,4,4)),
    ((4,3,2,1)+tuple([0]*16)+(1,1,1,1,2,2,2,2,3,3,4,4),
     (4,3,2,1)+tuple([0]*16)+(1,1,1,1,2,2,2,2,3,3,4,4)))
def expected_schedule(index,batch=0):
    if batch not in (0,1):raise ValueError('Only two separately bounded capture batches')
    with overrides(base,VERSION=f'bidirectional-longhold-batch{batch}-v27-v1',PATTERNS=PATTERNS_BY_BATCH[batch]):
        return base.expected_schedule(index)
def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Existing v27 only; no flash or extra qualification')
    if a.longhold_batch not in (0,1):raise ValueError('Unknown batch')
    with overrides(base,VERSION=f'bidirectional-longhold-batch{a.longhold_batch}-v27-v1',PATTERNS=PATTERNS_BY_BATCH[a.longhold_batch]):return base.validate(a)
def run(a):
    validate(a)
    with overrides(base,VERSION=f'bidirectional-longhold-batch{a.longhold_batch}-v27-v1',PATTERNS=PATTERNS_BY_BATCH[a.longhold_batch]):return base.run(a)
