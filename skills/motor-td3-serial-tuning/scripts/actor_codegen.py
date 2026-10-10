#!/usr/bin/env python3
"""Export the verified small MATLAB Actor to dependency-free C99, then test on host."""
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from session_checks import load_json, nonfinite_paths, number
from motor_runtime import FIELDS, f32


def cfloat(value):
    text = format(value, '.9g')
    if '.' not in text and 'e' not in text.lower():
        text += '.0'
    return text + 'f'


def export(source, output):
    m = load_json(source)
    if (m.get('schema_version') != 1 or m.get('architecture') != '10-16-relu-16-relu-2-tanh'
            or m.get('state_fields') != FIELDS or nonfinite_paths(m)):
        raise ValueError('Unsupported model/normalization contract')
    for key in ('policy_version', 'profile_id', 'normalization_id', 'action_mapping_id'):
        if not isinstance(m.get(key), str) or not m[key]:
            raise ValueError('Missing model identity: ' + key)
    sizes = [(16, 10), (16, 16), (2, 16)]
    for w, b, (rows, cols) in zip(m['weights'], m['biases'], sizes):
        if (len(w) != rows or any(len(row) != cols for row in w) or len(b) != rows
                or not all(number(x) for row in w for x in row)
                or not all(number(x) for x in b)):
            raise ValueError('Invalid weight shape/value')
    if len(m['weights']) != 3 or len(m['biases']) != 3:
        raise ValueError('Expected three affine layers')
    for matrix, bias in zip(m['weights'],m['biases']):
        for value in [x for row in matrix for x in row] + bias:
            if not math.isfinite(f32(value)):
                raise ValueError('Weights must fit float32')
    if len(m['state_scale']) != 10 or not all(number(x) and x > 0 for x in m['state_scale']):
        raise ValueError('Invalid state scales')
    c = m['controller']
    for g in ('kp', 'ki'):
        if not all(number(c[g + '_' + k]) for k in ('min', 'max')) or not number(c['max_' + g + '_step']):
            raise ValueError('Invalid gain contract')
        if not 0 <= c[g + '_min'] < c[g + '_max'] or not 0 < c['max_' + g + '_step'] <= c[g + '_max'] - c[g + '_min']:
            raise ValueError('Invalid gain limits')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    header = '''#ifndef MOTOR_ACTOR_H
#define MOTOR_ACTOR_H
/* raw: rpm,rpm,rpm,rpm,A,A,V,Kp,Ki,ms. No allocation, no training on MCU.
 * Return 0 on invalid input; caller must invoke its validated safe-stop path.
 * Inference must not bypass the independent firmware guard. */
int motor_actor_predict(const float raw[10], float action[2], float gains[2]);
#endif
'''
    lines = ['#include "motor_actor.h"', '#include <math.h>']
    def array(name, values):
        lines.append('static const float %s[%d] = {%s};' % (name, len(values), ','.join(cfloat(x) for x in values)))
    for i in range(3):
        array('w%d' % i, [x for row in m['weights'][i] for x in row])
        array('b%d' % i, m['biases'][i])
    array('scale', m['state_scale'])
    array('lower', [c['kp_min'], c['ki_min']])
    array('upper', [c['kp_max'], c['ki_max']])
    lines.append('static const double step[2] = {%s,%s};' %
                 (format(c['max_kp_step'],'.17g'),format(c['max_ki_step'],'.17g')))
    lines.append('''
static void dense(const float *x, float *y, const float *w, const float *b, int rows, int cols, int relu) {
    int r,c; for(r=0;r<rows;r++) { float s=b[r];
        for(c=0;c<cols;c++) s += w[r*cols+c]*x[c];
        y[r] = relu ? fmaxf(0.0f,s) : tanhf(s);
    }
}
int motor_actor_predict(const float raw[10], float action[2], float gains[2]) {
    float x[10], h1[16], h2[16]; int i;
    if (!raw || !action || !gains) return 0;
    for(i=0;i<10;i++) { if(!isfinite(raw[i])) return 0;
        x[i]=fmaxf(-5.0f,fminf(5.0f,raw[i]/scale[i]));
    }
    for(i=0;i<2;i++) if(raw[7+i]<lower[i] || raw[7+i]>upper[i]) return 0;
    dense(x,h1,w0,b0,16,10,1); dense(h1,h2,w1,b1,16,16,1); dense(h2,action,w2,b2,2,16,0);
    for(i=0;i<2;i++) {
        float current=raw[7+i];
        double lo=fmax((double)lower[i],(double)current-step[i]), hi=fmin((double)upper[i],(double)current+step[i]);
        gains[i]=(float)((double)current+(action[i]>=0.0f ? (hi-current)*action[i] : (current-lo)*action[i]));
        if((double)gains[i]<lo || (double)gains[i]>hi) gains[i]=nextafterf(gains[i],current);
        if(!isfinite(action[i]) || !isfinite(gains[i]) || gains[i]<lower[i] || gains[i]>upper[i]) return 0;
    }
    return 1;
}
''')
    (output / 'motor_actor.h').write_text(header, encoding='utf-8', newline='\n')
    (output / 'motor_actor.c').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
              for name in ('motor_actor.c', 'motor_actor.h')}
    manifest = {k: m[k] for k in ('policy_version', 'profile_id', 'normalization_id', 'action_mapping_id', 'simulation_only')}
    manifest.update(schema_version=1, files_sha256=hashes, parameter_count=482,
                    weight_bytes=1928, workspace_float_bytes=168,
                    dynamic_allocation=False, hardware_deployment_approved=False,
                    source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest())
    (output / 'deployment-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def verify(output, reference, compiler):
    output = Path(output).resolve()
    # All generated runner/build files go into the caller-specified artifact directory.
    runner = output / 'parity_runner.c'
    runner.write_text('''#include "motor_actor.h"
#include <stdio.h>
#include <math.h>
int main(void) { float raw[10],a[2]={0},g[2]={0}; int i;
    while(1) { for(i=0;i<10;i++) if(scanf("%f",&raw[i])!=1) return 0;
        int ok=motor_actor_predict(raw,a,g);
        printf("%d %.9g %.9g %.9g %.9g\\n",ok,a[0],a[1],g[0],g[1]);
    }
}
''', encoding='utf-8')
    exe = output / 'parity_runner.exe'
    subprocess.run([compiler, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(output / 'motor_actor.c'), str(runner), '-lm', '-o', str(exe)], check=True, capture_output=True, text=True)
    refs = load_json(reference)
    inputs = '\n'.join(' '.join(str(x) for x in row['raw_state']) for row in refs) + '\n'
    # Invalid sensor value must be rejected, not clipped into a plausible input.
    inputs += 'nan ' + ' '.join(str(x) for x in refs[0]['raw_state'][1:]) + '\n'
    result = subprocess.run([str(exe)], input=inputs, check=True, capture_output=True, text=True)
    actual = result.stdout.splitlines()
    if len(actual) != len(refs) + 1:
        raise ValueError('Incomplete host inference output')
    action_error = gain_error = 0.0
    for row, line in zip(refs, actual):
        values = line.split()
        if values[0] != '1':
            raise ValueError('C rejected a valid MATLAB reference')
        predicted = [float(x) for x in values[1:]]
        if not all(math.isfinite(x) for x in predicted):
            raise ValueError('Non-finite C output')
        action_error = max(action_error, *(abs(a-b) for a, b in zip(predicted[:2], row['action'])))
        gain_error = max(gain_error, *(abs(a-b) for a, b in zip(predicted[2:], row['gains'])))
    if actual[-1].split()[0] != '0' or action_error > 2e-6 or gain_error > 2e-9:
        raise ValueError('MATLAB/C parity or invalid-input rejection failed')
    report = dict(host_c_parity_passed=True, vectors=len(refs), max_action_error=action_error,
                  max_gain_error=gain_error, nan_rejected=True, processor_in_loop_verified=False)
    (output / 'c-parity-summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reference', help='MATLAB reference JSON; enables host verification')
    parser.add_argument('--compiler', default='gcc')
    args = parser.parse_args()
    report = export(args.model,args.output)
    if args.reference:
        report['verification'] = verify(args.output,args.reference,args.compiler)
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
