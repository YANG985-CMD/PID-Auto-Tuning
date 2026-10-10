"""Test raw-ADC thermal feed and locked SpeedLoop glue without hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import build_speedloop_diagnostic as builder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--compiler', default='gcc')
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if os.name == 'nt' and Path(r'E:\simulink\_codex_tmp').resolve() not in out.parents:
        raise ValueError('Windows test output must be under the approved temp root')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a fresh task directory')
    out.mkdir(parents=True, exist_ok=True)
    fw = Path(__file__).resolve().parents[1]/'firmware'
    env = os.environ.copy()
    env.update(TEMP=str(out), TMP=str(out), TMPDIR=str(out))
    (out/'main.h').write_text('#include <stdint.h>\nstatic inline uint32_t __get_PRIMASK(void){return 0;}\n'
                             'static inline void __disable_irq(void){}\nstatic inline void __set_PRIMASK(uint32_t p){(void)p;}\n', encoding='ascii')
    results = {}
    for name, host, extra in (
        ('feed', 'thermal_feed_host.c', []),
        ('speedloop', 'speedloop_thermal_host.c', [str(fw/'motor_td3_speedloop_thermal.c')])):
        exe = out/(name+('.exe' if os.name == 'nt' else ''))
        cmd = [args.compiler, '-std=c99', '-O2', '-pipe', '-fno-fast-math', '-ffp-contract=off',
               '-Wall', '-Wextra', '-Werror', '-DMOTOR_TD3_SPEEDLOOP_DIAGNOSTIC',
               '-DMOTOR_TD3_SPEEDLOOP_WATCHDOG', '-I', str(out), '-I', str(fw),
               str(fw/'motor_td3_thermal.c'), str(fw/'motor_td3_thermal_feed.c'),
               str(fw/'motor_td3_thermal_can.c'),
               str(fw/'tests'/host), *extra, '-lm', '-o', str(exe)]
        build = subprocess.run(cmd, env=env, capture_output=True, text=True)
        (out/(name+'-build.log')).write_text(build.stdout+build.stderr, encoding='utf-8')
        if build.returncode:
            raise RuntimeError('Build failed; inspect '+name+'-build.log')
        run = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        (out/(name+'-run.log')).write_text(run.stdout+run.stderr, encoding='utf-8')
        if run.returncode:
            raise RuntimeError('Fault tests failed; inspect '+name+'-run.log')
        results[name] = json.loads(run.stdout)
    try:
        builder.build(SimpleNamespace(thermal_audit=True, watchdog=False))
    except ValueError:
        results['unlocked_build_rejected_before_source_access'] = True
    else:
        raise AssertionError('Thermal audit accepted a build without watchdog lock')
    sources = ('motor_td3_thermal.c', 'motor_td3_thermal.h', 'motor_td3_thermal_feed.c',
               'motor_td3_thermal_feed.h', 'motor_td3_speedloop_thermal.c', 'motor_td3_speedloop_thermal.h',
               'motor_td3_thermal_can.c', 'motor_td3_thermal_can.h',
               'tests/thermal_feed_host.c', 'tests/speedloop_thermal_host.c')
    results.update(schema_version=1, passed=True, hardware_accessed=False,
                   current_gain_calibrated=False, thermal_protection_verified=False,
                   source_sha256={s: hashlib.sha256((fw/s).read_bytes()).hexdigest() for s in sources})
    (out/'summary.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
