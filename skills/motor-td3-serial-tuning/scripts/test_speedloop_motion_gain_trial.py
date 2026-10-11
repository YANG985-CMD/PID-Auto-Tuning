"""Offline checks for actual-action validation and physical stop ordering."""
import unittest
from speedloop_motion_gain_trial import check_telemetry, planned_gains, shutdown, f32
from speedloop_motion_handshake import REGS, PHASE_MASK
import can_transport as wire


class Checks(unittest.TestCase):
    def setUp(self):
        self.t = dict(type='telemetry', seq=2, t_us=20000, t_apply_us=12000,
                      applied_seq=1, fault=0, enabled=True, temperature_c=None,
                      **{k: 0. for k in wire.FLOATS if k != 'temperature_c'})
        self.t.update(kp=f32(.003389), ki=f32(.00144), vbus=24)
        self.sent = {1: dict(kp=self.t['kp'], ki=self.t['ki'], source_t_us=10000, expires_us=110000)}
        self.last = dict(self.t, seq=1, t_us=10000, applied_seq=0)

    def test_actual_ack_valid(self):
        check_telemetry(self.t, self.last, self.sent)

    def test_unknown_action_rejected(self):
        self.t['applied_seq'] = 2
        with self.assertRaises(RuntimeError): check_telemetry(self.t, self.last, self.sent)

    def test_echo_does_not_replace_actual_gain(self):
        self.t['kp'] *= 1.01
        with self.assertRaises(RuntimeError): check_telemetry(self.t, self.last, self.sent)

    def test_apply_must_follow_source_state(self):
        self.t['t_apply_us'] = 9000
        with self.assertRaises(RuntimeError): check_telemetry(self.t, self.last, self.sent)

    def test_gap_rejected(self):
        self.t['seq'] = 3
        with self.assertRaises(RuntimeError): check_telemetry(self.t, self.last, self.sent)

    def test_fault_rejected(self):
        self.t['fault'] = 9
        with self.assertRaises(RuntimeError): check_telemetry(self.t, self.last, self.sent)

    def test_small_probe_and_return(self):
        base = planned_gains(2399)
        probe = planned_gains(2400)
        self.assertEqual(base, planned_gains(2700))
        self.assertLess(probe[0]-base[0], .00027112)
        self.assertEqual(base[1], probe[1])

    def test_hardware_off_precedes_halt(self):
        class Target:
            def __init__(self):
                self.reg = dict(zip(REGS.values(), [PHASE_MASK|0x1000, 0x8000, 0xaa95ffff,
                                                    0xabaaaaaa, 0x700, 0xe000, 0x468]))
                self.halted = False
            def read32(self, addr): return self.reg.get(addr, 0)
            def write32(self, addr, value):
                self.reg[addr] = value
                if addr in (0x48000018, 0x48000418): self.reg[addr-4] &= ~(value >> 16)
            def write8(self, addr, value): self.reg[addr] = value
            def halt(self):
                assert not self.read32(REGS['tim1_bdtr']) & 0x8000
                assert not self.read32(REGS['tim1_ccer']) & PHASE_MASK
                assert not self.read32(REGS['gpioa_odr']) & 0x700
                assert not self.read32(REGS['gpiob_odr']) & 0xe000
                self.halted = True
        target = Target()
        shutdown(target, {'Motor_state': 0x20000000})
        self.assertTrue(target.halted)


if __name__ == '__main__': unittest.main()
