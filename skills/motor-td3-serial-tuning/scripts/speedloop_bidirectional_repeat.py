"""Second finite v27 capture: add independent low-target switch/bridge holds."""
import speedloop_bidirectional_v27 as base
from speedloop_bidirectional_v27 import IDENTITY,IMAGE_SHA,HEX_SHA,IMAGE_BYTES,PRIOR_SHA,PRIOR_BYTES,LEVELS,KI,BASE_INDEX,ReferenceProbe,reference_matches,reference_rpm,HALL_READ_PROFILE,sha,read
from speedloop_duration_review import overrides
VERSION='bidirectional-bridge-hold-repeat-v27-v1'
PATTERNS=((4,3,2,1,0,1,1,2,3,4,4,3,2,1,0,1,2,3,4,3,2,1,0,1,1,2,3,4,3,2,1,0),
          (4,3,2,1,0,1,2,3,4,3,2,1,0,1,1,2,3,4,4,3,2,1,0,1,2,3,4,3,2,1,0,1))
PLATEAU_START_MS=base.PLATEAU_START_MS;PLATEAU_END_MS=base.PLATEAU_END_MS;PLATEAU_MS=base.PLATEAU_MS
def expected_schedule(index):
    with overrides(base,VERSION=VERSION,PATTERNS=PATTERNS):return base.expected_schedule(index)
def qualification_schedule():raise ValueError('Repeat capture cannot request another qualification')
def validate(a):
    if a.phase not in ('prepare','trial'):raise ValueError('Repeat reuses exact v27; no flashing or qualification')
    with overrides(base,VERSION=VERSION,PATTERNS=PATTERNS):return base.validate(a)
def run(a):
    validate(a)
    with overrides(base,VERSION=VERSION,PATTERNS=PATTERNS):return base.run(a)
