"""Fit phase current ADC gain/offset from an external reference-current CSV.

This is an offline fit only. It never opens a probe, writes MCU parameters,
changes a DAC threshold, or approves motor control.
CSV columns: phase,reference_A,adc_code. One row is one synchronized sample.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

PHASES=('A','B','C')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_rows(path):
    rows=[]
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        required={'phase','reference_A','adc_code'}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError('CSV must contain phase,reference_A,adc_code columns')
        for n,row in enumerate(reader,2):
            phase=str(row.get('phase','')).strip().upper()
            try: current=float(row['reference_A']);adc=float(row['adc_code'])
            except (TypeError,ValueError) as exc: raise ValueError(f'line {n}: invalid numeric value') from exc
            if phase not in PHASES or not math.isfinite(current) or not math.isfinite(adc):
                raise ValueError(f'line {n}: invalid phase or non-finite value')
            if not 0<=adc<=4095: raise ValueError(f'line {n}: ADC code outside 0..4095')
            rows.append((phase,current,adc))
    if not rows: raise ValueError('CSV has no rows')
    return rows

def fit_phase(rows):
    points=[(current,adc) for current,adc in rows]
    if len(points)<6 or len({current for current,_ in points})<3:
        raise ValueError('Each phase needs at least 6 samples at 3 current levels')
    xs=[adc for _,adc in points];ys=[current for current,_ in points]
    xm=sum(xs)/len(xs);ym=sum(ys)/len(ys)
    denom=sum((x-xm)**2 for x in xs)
    if denom<=1e-12: raise ValueError('ADC codes have no span')
    slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denom
    intercept=ym-slope*xm
    if not math.isfinite(slope) or abs(slope)<1e-12: raise ValueError('Fitted gain is zero')
    predicted=[slope*x+intercept for x in xs]
    residual=[y-p for y,p in zip(ys,predicted)]
    ssres=sum(e*e for e in residual);sstot=sum((y-ym)**2 for y in ys)
    r2=1.0-ssres/sstot if sstot>1e-12 else 0.0
    return dict(samples=len(points),current_levels=sorted(set(ys)),adc_min=min(xs),adc_max=max(xs),
        gain_a_per_count=slope,intercept_a=intercept,zero_adc=-intercept/slope,
        r2=r2,rms_residual_a=math.sqrt(ssres/len(points)),max_abs_residual_a=max(abs(e) for e in residual),
        bipolar_reference=min(ys)<0<max(ys),rail_samples=sum(x in (0,4095) for x in xs))

def fit(rows):
    grouped={phase:[] for phase in PHASES}
    for phase,current,adc in rows:grouped[phase].append((current,adc))
    phases={phase:fit_phase(grouped[phase]) for phase in PHASES}
    return dict(schema_version=1,mode='offline-current-calibration-fit',phases=phases,
        quality=dict(all_bipolar=all(v['bipolar_reference'] for v in phases.values()),
            all_nonrail=all(v['rail_samples']==0 for v in phases.values()),
            min_r2=min(v['r2'] for v in phases.values()),
            max_rms_residual_a=max(v['rms_residual_a'] for v in phases.values())),
        current_gain_calibrated=False,current_threshold_calibrated=False,
        hardware_shutoff_verified=False,device_write=False,motor_control_approved=False,
        protection_threshold_candidate=None,
        limitations=['Fit requires synchronized reference current and ADC samples',
            'No fitted value is written to firmware or used as a DAC trip threshold',
            'Acceptance limits and protection target must be supplied by the hardware test plan'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv');p.add_argument('--output',required=True)
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('Use a new empty output directory')
    rows=load_rows(a.csv);result=fit(rows);result['source_csv_sha256']=sha(a.csv)
    (out/'fit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
