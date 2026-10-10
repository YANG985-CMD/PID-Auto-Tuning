"""Fault and command-boundary checks; no debug probe or PCAN adapter opened."""
from collections import deque
import struct
from types import SimpleNamespace
import unittest

import can_transport as wire
import speedloop_can_capture as diag

NONCE, BOOT = 0x1234567812345678, 0x1020304050607080


def hello(**changes):
    obj = dict(type='hello_reply', firmware_id=diag.IDENTITY,
               profile_id=diag.IDENTITY, capabilities=[])
    obj.update(changes)
    return wire.fragment(wire.pack(obj, NONCE, BOOT), 2)


def status(flags=3, age=5, fault=12, hall=3):
    return struct.pack('<BBHBBH', 1, fault, flags, hall, 0, age)


def collector():
    c = diag.Collector(NONCE, BOOT, lambda row: None)
    for f in hello():
        c.feed(0x621, f, .01, 10000)
    return c


class Clock:
    now = 0.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Link:
    def __init__(self, clock, fail=False):
        self.clock, self.fail = clock, fail
        self.sent = []
        self.rx = deque((.01, 0x621, f) for f in hello())
        for i in range(11):
            at = .02 + .09*i
            for identifier, data in ((0x622, status()), (0x623, struct.pack('<ff', .003389, .00144)),
                                     (0x624, struct.pack('<ff', 24, .03)),
                                     (0x625, struct.pack('<ff', 0, 0))):
                self.rx.append((at, identifier, data))
        self.basic = SimpleNamespace(PCAN_ERROR_OK=0, PCAN_ERROR_QRCVEMPTY=32, PCAN_MESSAGE_STANDARD=0)
        self.api, self.handle = self, 1

    value = staticmethod(int)

    def mode(self):
        pass

    def send(self, frame):
        self.sent.append(frame)

    def check(self, status):
        if status:
            raise wire.WireError('Injected driver failure')

    def Read(self, handle):
        if self.fail:
            return 8, None, None
        if not self.rx or self.rx[0][0] > self.clock():
            return 32, None, None
        at, identifier, data = self.rx.popleft()
        return (0, SimpleNamespace(ID=identifier, MSGTYPE=0, LEN=8, DATA=data),
                SimpleNamespace(micros=int(at*1e6) % 1000, millis=int(at*1000), millis_overflow=0))


class CaptureTests(unittest.TestCase):
    def test_nominal_stream_only_one_hello(self):
        clock = Clock()
        link = Link(clock)
        c = diag.Collector(NONCE, BOOT, lambda row: None)
        report = diag.capture(link, c, 1, clock, clock.sleep)
        self.assertEqual(report['hello_requests'], 1)
        packet = wire.Reassembler()
        obj = None
        for f in link.sent:
            data = packet.feed(f, 0)
            if data:
                obj, meta = wire.unpack(data)
        self.assertEqual(obj, dict(type='hello', profile_id=diag.IDENTITY))
        self.assertEqual(c.cycles, 11)
        self.assertEqual(c.ranges['hall_speed_rpm'], (0., 0.))

    def test_bad_identity_or_capability_refused(self):
        for change in (dict(firmware_id='other'), dict(profile_id='other'),
                       dict(capabilities=['atomic_gains'])):
            with self.subTest(change=change), self.assertRaises(wire.WireError):
                c = diag.Collector(NONCE, BOOT, lambda row: None)
                for f in hello(**change):
                    c.feed(0x621, f, .01, 0)

    def test_nonce_and_boot_mismatch_refused(self):
        for nonce, boot in ((NONCE+1, BOOT), (NONCE, BOOT+1)):
            with self.subTest(nonce=nonce, boot=boot), self.assertRaises(wire.WireError):
                c = diag.Collector(nonce, boot, lambda row: None)
                for f in hello():
                    c.feed(0x621, f, .01, 0)

    def test_output_adc_fault_and_hall_checks(self):
        for data in (status(flags=7), status(flags=19), status(flags=35), status(flags=2),
                     status(age=31), status(fault=10), status(hall=7), status(flags=11)):
            with self.subTest(data=data.hex()), self.assertRaises(wire.WireError):
                collector().feed(0x622, data, .02, 0)

    def test_reorder_and_nonfinite_refused(self):
        c = collector()
        with self.assertRaises(wire.WireError):
            c.feed(0x623, b'\0'*8, .02, 0)
        c.feed(0x622, status(), .02, 0)
        with self.assertRaises(wire.WireError):
            c.feed(0x623, struct.pack('<ff', float('nan'), 0), .02, 0)

    def test_missing_handshake_and_stream_timeout(self):
        c = diag.Collector(NONCE, BOOT, lambda row: None)
        with self.assertRaises(wire.WireError):
            c.feed(0x622, status(), .01, 0)
        with self.assertRaises(wire.WireError):
            c.check_freshness(1.1, 0)
        c = collector()
        c.feed(0x622, status(), .02, 0)
        with self.assertRaises(wire.WireError):
            c.check_freshness(.6, 0)

    def test_driver_failure_no_retry(self):
        clock = Clock()
        link = Link(clock, fail=True)
        with self.assertRaises(wire.WireError):
            diag.capture(link, diag.Collector(NONCE, BOOT, lambda row: None), 1, clock, clock.sleep)
        self.assertEqual(len(link.sent), len(wire.fragment(wire.pack(dict(type='hello', profile_id=diag.IDENTITY), NONCE), 1)))

    def test_halt_before_close_and_cleanup_on_failed_halt(self):
        for fail in (False, True):
            calls = []
            def hold():
                calls.append('halt')
                if fail:
                    raise wire.WireError('Injected hold failure')
                return dict(tim1_ccer=0)
            link = SimpleNamespace(close=lambda: calls.append('close'))
            report = dict(verified=True)
            diag.finish(link, hold, report)
            self.assertEqual(calls, ['halt', 'close'])
            self.assertTrue(report['adapter_released'])
            self.assertEqual(report['verified'], not fail)

    def test_preflight_rejects_unsafe_ram_and_pwm(self):
        manifest = dict(firmware_id=diag.IDENTITY, capabilities=0, bin_sha256=diag.AUDITED_BIN_SHA,
                        image_bytes=diag.IMAGE_BYTES, motion_enable_implemented=False,
                        gain_application_implemented=False, forbidden_motion_symbols_absent=True,
                        symbols={n: 0x20000000+i*8 for i, n in enumerate(diag.RAM_NAMES)})
        diag.validate_manifest(manifest)
        words = dict(diag.REGISTERS)
        words.update(manifest['symbols'])
        values = dict(tim1_cr1=0x120, tim1_ccer=0, tim1_bdtr=0x02023078, debug_id=0x20036468,
                      endpoint_ready=1, initialized=1, irq_fault=0, Motor_state=0,
                      motor_td3_g431_debugger_boot_token=0)
        def trace():
            return ('Core 0 (None):  Running\n' +
                    '\n'.join(f'{words[n]:08x}:  {v:0{2 if n == "Motor_state" else 8}x}' for n, v in values.items()) +
                    f'\n{manifest["symbols"][diag.RAM_NAMES[-1]]+4:08x}:  00000000\n')
        self.assertEqual(diag.parse_preflight(trace(), manifest)['endpoint_ready'], 1)
        for name, value in (('tim1_cr1', 0x121), ('tim1_ccer', 0x1000), ('tim1_bdtr', 0x0202b078),
                            ('endpoint_ready', 0), ('irq_fault', 1), ('Motor_state', 1),
                            ('motor_td3_g431_debugger_boot_token', 1)):
            old = values[name]
            values[name] = value
            with self.subTest(name=name), self.assertRaises(wire.WireError):
                diag.parse_preflight(trace(), manifest)
            values[name] = old


if __name__ == '__main__':
    unittest.main()
