"""Offline package/link/source validation. Does not import hardware modules."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

def audit(root,output):
    root,output=Path(root).resolve(),Path(output).resolve();links=0;sources=0;missing=[]
    for p in [root/'SKILL.md',*sorted((root/'references').rglob('*.md'))]:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
            if target.startswith(('https:','http:','#','mailto:')):continue
            name=target.strip('<>').split('#')[0]
            if not name:continue
            links+=1
            if not (p.parent/name).resolve().is_file():missing.append(dict(source=str(p.relative_to(root)),target=target))
    for p in (root/'scripts').glob('*.py'):
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p));sources+=1
    for name in ('scripts/speedloop_lower16_probe.py','scripts/analyze_speedloop_plateaus.py',
        'scripts/rebuild_speedloop_decision_replay.py','matlab/trainMotorElapsedTD3.m',
        'matlab/runSpeedLoopAsyncTraining.m','matlab/verifySpeedLoopPlateaus.m'):
        if not (root/name).is_file():missing.append(dict(source='declared current entry',target=name))
    result=dict(passed=not missing,skill=str(root),verified_local_links=links,
        python_sources_parsed=sources,missing=missing,hardware_accessed=False,
        skill_sha256=hashlib.sha256((root/'SKILL.md').read_bytes()).hexdigest())
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();raise SystemExit(0 if audit(a.root,a.output)['passed'] else 1)
