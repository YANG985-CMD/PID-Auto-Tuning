#!/usr/bin/env python3
"""Compile and exercise the MCU protocol/guard on the host; never flashes hardware."""
import argparse
import ctypes as ct
import json
import math
import subprocess
import sys
import zlib
from pathlib import Path
from motor_runtime import decode_frame, encode_frame


class Limits(ct.Structure):
    _fields_=[(k,ct.c_float) for k in ('kp_min','kp_max','ki_min','ki_max','kp_step','ki_step','kp_baseline','ki_baseline',
              'current_limit','speed_limit','vbus_min','vbus_max','temperature_limit')]+[(k,ct.c_uint32) for k in
              ('lease_max_us','link_timeout_us','trial_max_us','command_max')]


class Guard(ct.Structure):
    _fields_=[('limits',Limits),('kp',ct.c_float),('ki',ct.c_float)]+[(k,ct.c_uint64) for k in
              ('deadline_us','last_rx_us','started_us','last_tick_us','t_apply_us')]+[(k,ct.c_uint32) for k in
              ('applied_seq','commands')]+[('enabled',ct.c_int),('fault',ct.c_int)]


class Command(ct.Structure):
    _fields_=[('type',ct.c_int),('profile_id',ct.c_char*96),('command_seq',ct.c_uint32),('lease_ms',ct.c_uint32)]+[
              (k,ct.c_float) for k in ('kp','ki','speed_ref')]


class Telemetry(ct.Structure):
    _fields_=[('t_us',ct.c_uint64),('t_apply_us',ct.c_uint64)]+[(k,ct.c_uint32) for k in ('seq','applied_seq','fault')]+[
              ('enabled',ct.c_int)]+[(k,ct.c_float) for k in ('speed_ref','speed','error_history','integral_output',
              'current','vbus','temperature_c','kp','ki','elapsed_ms')]


def run(output,compiler):
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).resolve().parents[1]/'firmware'
    library=output/('guard.dll' if sys.platform=='win32' else 'guard.so')
    subprocess.run([compiler,'-std=c99','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                    str(source/'motor_td3_guard.c'),str(source/'motor_td3_protocol.c'),'-lm','-o',str(library)],
                   check=True,capture_output=True,text=True)
    lib=ct.CDLL(str(library))
    lib.motor_td3_init.argtypes=[ct.POINTER(Guard),ct.POINTER(Limits)]
    lib.motor_td3_begin.argtypes=[ct.POINTER(Guard),ct.c_uint64,ct.c_uint32]
    lib.motor_td3_apply.argtypes=[ct.POINTER(Guard),ct.c_uint64,ct.c_uint32,ct.c_float,ct.c_float,ct.c_uint32]
    lib.motor_td3_tick.argtypes=[ct.POINTER(Guard),ct.c_uint64,ct.c_float,ct.c_float,ct.c_float,ct.c_float,ct.c_int]
    lib.motor_td3_decode.argtypes=[ct.c_char_p,ct.c_size_t,ct.POINTER(Command)]
    lib.motor_td3_encode_hello.argtypes=[ct.c_char_p,ct.c_size_t,ct.c_char_p,ct.c_char_p,ct.c_char_p]
    lib.motor_td3_encode_telemetry.argtypes=[ct.c_char_p,ct.c_size_t,ct.c_char_p,ct.POINTER(Telemetry)]
    limits=Limits(.0025,.0043,.0008,.0022,.00008,.00008,.003389,.00144,4,1800,20,28,75,5000000,5000000,4000000,30)
    tests=[]
    def fresh():
        guard=Guard(); assert lib.motor_td3_init(ct.byref(guard),ct.byref(limits))
        assert lib.motor_td3_begin(ct.byref(guard),1000,2000000)
        return guard
    g=fresh()
    assert lib.motor_td3_apply(ct.byref(g),2000,1,.0034,.00144,2000000)
    assert g.applied_seq==1 and g.t_apply_us==2000 and g.enabled
    tests.append('atomic-applied-feedback')
    assert not lib.motor_td3_apply(ct.byref(g),3000,1,.0034,.00144,2000000) and g.fault
    assert not lib.motor_td3_begin(ct.byref(g),4000,2000000)
    tests.append('sequence-and-fault-latch')
    for name,kp,ki in [('nan',math.nan,.00144),('inf',math.inf,.00144),('gain-range',.02,.00144),('gain-step',.004,.00144)]:
        g=fresh(); assert not lib.motor_td3_apply(ct.byref(g),2000,1,kp,ki,2000000)
        assert not g.enabled and g.fault; tests.append(name)
    for name,now,current,speed,vbus,temp,estop in [
        ('overcurrent',2000,4,0,24,30,0),('overspeed',2000,0,1800,24,30,0),
        ('bus',2000,0,0,19,30,0),('temperature',2000,0,0,24,75,0),
        ('sensor-nan',2000,math.nan,0,24,30,0),('estop',2000,0,0,24,30,1),
        ('lease',2001000,0,0,24,30,0),('clock-reset',999,0,0,24,30,0)]:
        g=fresh(); lib.motor_td3_tick(ct.byref(g),now,current,speed,vbus,temp,estop)
        assert not g.enabled and g.fault; tests.append(name)
    g=fresh(); g.limits.link_timeout_us=500
    lib.motor_td3_tick(ct.byref(g),2000,0,0,24,30,0); assert g.fault==8
    tests.append('independent-link-timeout')
    g=fresh(); g.limits.trial_max_us=500
    lib.motor_td3_tick(ct.byref(g),2000,0,0,24,30,0); assert g.fault==9
    tests.append('independent-trial-limit')
    for cmd in [dict(type='hello',profile_id='mock-speed-pi-v1'),dict(type='begin',profile_id='mock-speed-pi-v1',speed_ref=500,lease_ms=5000),
                dict(type='gains',command_seq=1,kp=.003389,ki=.00144,lease_ms=5000),dict(type='stop')]:
        frame=encode_frame(cmd); parsed=Command()
        assert lib.motor_td3_decode(frame,len(frame),ct.byref(parsed))
    tests.append('python-commands-decoded-by-c')
    for payload in [b'{"type":"stop","type":"stop"}',b'{"type":"stop","x":1}',
                    b'{"type":"gains","command_seq":1,"kp":1e999,"ki":0.1,"lease_ms":1}',
                    b'{"type":"begin","profile_id":"x","speed_ref":NaN,"lease_ms":1}',
                    b'{"type":"stop",}',b'{"type":"gains","kp":01}',b'{"type":"hello","profile_id":"x\\ny"}']:
        frame=payload+b'*'+('%08x'%zlib.crc32(payload)).encode()+b'\n'
        assert not lib.motor_td3_decode(frame,len(frame),ct.byref(Command()))
    frame=encode_frame(dict(type='stop')).replace(b'stop',b'stopx')
    assert not lib.motor_td3_decode(frame,len(frame),ct.byref(Command()))
    tests.append('malformed-duplicate-crc-nan-command-rejection')
    buf=ct.create_string_buffer(1536)
    n=lib.motor_td3_encode_hello(buf,len(buf),b'mock-plant-v1',b'mock-speed-pi-v1',b'boot-1')
    hello=decode_frame(buf.raw[:n]); assert hello['protocol_id']=='motor-td3-json-crc-v1'
    t=Telemetry(123456,123000,3,1,0,1,500,490,15,.2,.3,24,30,.003389,.00144,100)
    n=lib.motor_td3_encode_telemetry(buf,len(buf),b'boot-1',ct.byref(t))
    f=decode_frame(buf.raw[:n]); assert f['t_us']==123456 and f['enabled'] and f['applied_seq']==1
    assert not lib.motor_td3_encode_hello(buf,8,b'x',b'y',b'z')
    tests.append('c-telemetry-crc-and-float32-readback')
    report=dict(passed=True,host_compiled=True,tests=tests,test_count=len(tests),
                hardware_access=False,independent_hardware_protection_verified=False)
    (output/'firmware-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True); parser.add_argument('--compiler',default='gcc')
    args=parser.parse_args(); run(args.output,args.compiler)
