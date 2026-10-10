"""Host fault tests for the MCU thermal budget. Does not access any hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--compiler', default='gcc')
    parser.add_argument('--arm-compiler', help='Optional GNU Arm compiler; compile object only, never flash')
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if os.name == 'nt':
        root = Path(r'E:\simulink\_codex_tmp').resolve()
        if root not in out.parents:
            raise ValueError('Windows test output must be inside the approved task temp root')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a fresh task directory')
    out.mkdir(parents=True, exist_ok=True)
    fw = Path(__file__).resolve().parents[1] / 'firmware'
    exe = out / ('thermal-test.exe' if os.name == 'nt' else 'thermal-test')
    env = os.environ.copy()
    env.update(TEMP=str(out), TMP=str(out), TMPDIR=str(out))
    build = subprocess.run([args.compiler, '-std=c99', '-O2', '-pipe', '-Wall', '-Wextra', '-Werror',
                            '-I', str(fw), str(fw/'motor_td3_thermal.c'),
                            str(fw/'tests/thermal_host.c'), '-lm', '-o', str(exe)],
                           env=env, capture_output=True, text=True)
    (out/'build.log').write_text(build.stdout+build.stderr, encoding='utf-8')
    if build.returncode:
        raise RuntimeError('Thermal host build failed; inspect build.log')
    run = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    (out/'run.log').write_text(run.stdout+run.stderr, encoding='utf-8')
    if run.returncode:
        raise RuntimeError('Thermal fault test failed; inspect run.log')
    result = json.loads(run.stdout)
    result['source_sha256'] = {name: hashlib.sha256((fw/name).read_bytes()).hexdigest()
                               for name in ('motor_td3_thermal.c', 'motor_td3_thermal.h', 'tests/thermal_host.c')}
    result['arm_object_compiled'] = False
    result['linked_into_speedloop'] = False
    if args.arm_compiler:
        obj = out/'motor_td3_thermal.o'
        arm = subprocess.run([args.arm_compiler, '-std=c99', '-O2', '-pipe', '-Wall', '-Wextra', '-Werror',
                              '-mcpu=cortex-m4', '-mthumb', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard',
                              '-fno-fast-math', '-I', str(fw), '-c', str(fw/'motor_td3_thermal.c'),
                              '-o', str(obj)], env=env, capture_output=True, text=True)
        (out/'arm-build.log').write_text(arm.stdout+arm.stderr, encoding='utf-8')
        if arm.returncode:
            raise RuntimeError('Cortex-M4 object compilation failed; inspect arm-build.log')
        result['arm_object_compiled'] = True
        result['arm_object_sha256'] = hashlib.sha256(obj.read_bytes()).hexdigest()
        version = subprocess.run([args.arm_compiler, '--version'], env=env, capture_output=True, text=True, check=True)
        result['arm_compiler_version'] = version.stdout.splitlines()[0]
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
