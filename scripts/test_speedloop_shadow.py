import struct
import unittest

from speedloop_shadow import decode_snapshot


class ShadowTests(unittest.TestCase):
    def test_decode_complete_snapshot(self):
        frames = {
            0x641: bytes([0xB1, 2, 0, 0x84]) + struct.pack('<HH', 100, 12),
            0x642: struct.pack('<ff', 1000.0, 0.5),
            0x643: struct.pack('<ff', -0.25, 0.1),
            0x644: struct.pack('<ff', 24.1, 1.2),
            0x645: struct.pack('<ff', 0.0034, 0.0014),
            0x646: struct.pack('<II', 7, 20),
        }
        row = decode_snapshot(frames)
        self.assertTrue(row['phase_enabled'])
        self.assertEqual(row['state'], 2)
        self.assertAlmostEqual(row['speed_rpm'], 1000.0)
        self.assertEqual(row['host_sequence'], 7)

    def test_reject_incomplete_snapshot(self):
        with self.assertRaises(ValueError):
            decode_snapshot({0x641: bytes(8)})


if __name__ == '__main__':
    unittest.main()
