#!/usr/bin/env python3
"""Fault tests for PCAN capture; no driver or physical adapter is opened."""
import contextlib
import io
import types
import unittest

from can_monitor import ListenOnlyPcan, describe, main

B = types.SimpleNamespace(
    PCAN_CHANNEL_NAMES={"PCAN_USBBUS1": 81}, PCAN_BITRATES={500000: 28},
    PCAN_CHANNEL_CONDITION=13, PCAN_CHANNEL_AVAILABLE=1,
    PCAN_LISTEN_ONLY=8, PCAN_PARAMETER_ON=1, PCAN_ERROR_OK=0,
    PCAN_ERROR_QRCVEMPTY=32, PCAN_MESSAGE_RTR=1, PCAN_MESSAGE_EXTENDED=2,
    PCAN_MESSAGE_FD=4, PCAN_MESSAGE_ERRFRAME=64, PCAN_MESSAGE_STATUS=128)


class FakeApi:
    def __init__(self):
        self.calls, self.mode = [], 0
        self.condition, self.set_error, self.post_init_mode = 1, 0, 1
        self.message = types.SimpleNamespace(ID=0x1B, MSGTYPE=2, LEN=8, DATA=bytes(8))
        self.timestamp = types.SimpleNamespace(micros=3, millis=4, millis_overflow=1)
        self.read_error = 0

    def GetValue(self, channel, parameter):
        self.calls.append(("get", parameter))
        return 0, self.condition if parameter == 13 else self.mode

    def SetValue(self, channel, parameter, setting):
        self.calls.append(("set", parameter, setting))
        if not self.set_error:
            self.mode = setting
        return self.set_error

    def Initialize(self, channel, bitrate):
        self.calls.append(("initialize", channel, bitrate))
        self.mode = self.post_init_mode
        return 0

    def Read(self, channel):
        self.calls.append(("read",))
        return self.read_error, self.message, self.timestamp

    def Uninitialize(self, channel):
        self.calls.append(("uninitialize", channel))
        return 0

    def Write(self, *args):
        raise AssertionError("capture attempted CAN transmission")

    WriteFD = Reset = Write


class Tests(unittest.TestCase):
    def test_capture_presets_before_initialize_and_never_transmits(self):
        api = FakeApi()
        bus = ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        frame = bus.read()
        bus.close()
        self.assertLess(api.calls.index(("set", 8, 1)),
                        api.calls.index(("initialize", 81, 28)))
        self.assertEqual(frame["arbitration_id_hex"], "0x1B")
        self.assertTrue(frame["extended"])
        self.assertEqual(frame["adapter_timestamp_us"], 3 + 4000 + 1000 * (1 << 32))
        self.assertEqual(api.calls[-1], ("uninitialize", 81))

    def test_failed_listen_preset_does_not_initialize(self):
        api = FakeApi()
        api.set_error = 4
        with self.assertRaises(RuntimeError):
            ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        self.assertFalse(any(c[0] == "initialize" for c in api.calls))

    def test_failed_post_init_readback_closes_channel(self):
        api = FakeApi()
        api.post_init_mode = 0
        with self.assertRaises(RuntimeError):
            ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        self.assertEqual(api.calls[-1], ("uninitialize", 81))

    def test_occupied_channel_is_not_modified(self):
        api = FakeApi()
        api.condition = 3
        with self.assertRaises(RuntimeError):
            ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        self.assertFalse(any(c[0] in {"initialize", "set"} for c in api.calls))

    def test_invalid_bitrate_does_not_default_to_500k(self):
        api = FakeApi()
        with self.assertRaises(RuntimeError):
            ListenOnlyPcan(api, B, "PCAN_USBBUS1", 123456)
        self.assertEqual(api.calls, [])

    def test_mode_change_is_detected_before_next_read(self):
        api = FakeApi()
        bus = ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        api.mode = 0
        with self.assertRaises(RuntimeError):
            bus.read()
        bus.close()
        self.assertFalse(any(c[0] == "read" for c in api.calls))

    def test_remote_dlc_is_preserved_without_payload(self):
        api = FakeApi()
        api.message.MSGTYPE = 1
        frame = describe(api.message, api.timestamp, B)
        self.assertEqual(frame["dlc"], 8)
        self.assertEqual(frame["data_hex"], "")
        self.assertTrue(frame["remote"])

    def test_empty_queue_and_receive_fault_are_distinct(self):
        api = FakeApi()
        bus = ListenOnlyPcan(api, B, "PCAN_USBBUS1", 500000)
        api.read_error = 32
        self.assertIsNone(bus.read())
        api.read_error = 8
        with self.assertRaises(RuntimeError):
            bus.read()
        bus.close()

    def test_no_allow_live_and_nan_duration_fail_before_import(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for arguments in [[], ["--allow-live", "--duration", "nan"]]:
                with self.assertRaises(SystemExit) as e:
                    main(arguments)
                self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
