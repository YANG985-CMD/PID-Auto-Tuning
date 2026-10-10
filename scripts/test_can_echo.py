#!/usr/bin/env python3
"""No-hardware checks for the bounded active CAN diagnostic."""
import argparse
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/motor-td3-serial-tuning/scripts"))
import can_echo_pil as echo

ROOT = None


class Msg:
    def __init__(self): self.ID, self.MSGTYPE, self.LEN, self.DATA = 0, 0, 0, [0] * 8


BASIC = SimpleNamespace(PCAN_CHANNEL_NAMES={"PCAN_USBBUS1": 81}, PCAN_CHANNEL_CONDITION=1,
    PCAN_CHANNEL_AVAILABLE=1, PCAN_LISTEN_ONLY=2, PCAN_PARAMETER_OFF=0,
    PCAN_BITRATES={500000: 28}, PCAN_ERROR_OK=0, PCAN_ERROR_QRCVEMPTY=32,
    PCAN_MESSAGE_STANDARD=0, TPCANMsg=Msg)


class Api:
    def __init__(self):
        self.calls, self.condition, self.mode, self.status, self.reply = [], 1, 0, 0, None
        self.post_initialize_mode, self.bad_reply = None, False
    def GetValue(self, handle, parameter):
        self.calls.append("query")
        return (0, self.condition if parameter == 1 else self.mode)
    def SetValue(self, handle, parameter, mode):
        self.calls.append("preset"); self.mode = mode
        return self.status
    def Initialize(self, handle, bitrate):
        self.calls.append("initialize")
        if self.post_initialize_mode is not None: self.mode = self.post_initialize_mode
        return 0
    def Uninitialize(self, handle): self.calls.append("close"); return 0
    def Write(self, handle, message):
        self.calls.append("write")
        self.reply = Msg()
        self.reply.ID, self.reply.LEN, self.reply.DATA = 0x6E1, 8, list(message.DATA)
        if self.bad_reply: self.reply.DATA[4] ^= 1
        return 0
    def Read(self, handle):
        self.calls.append("read")
        if self.reply is None: return 32, Msg(), None
        return 0, self.reply, None


class EchoTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / self._testMethodName
        self.root.mkdir()
        self.args = SimpleNamespace(allow_live=True, board_supply_confirmed=True,
                                   motor_output_disabled_ack=True, build=str(self.root / "build"),
                                   output=str(self.root / "result"), channel="PCAN_USBBUS1")

    def test_missing_authorization_supply_or_output_ack_never_opens_hardware(self):
        for flag in ("allow_live", "board_supply_confirmed", "motor_output_disabled_ack"):
            setattr(self.args, flag, False)
            with patch.object(echo.pil, "session") as session, patch.object(echo, "PcanEndpoint") as can:
                with self.assertRaises(ValueError): echo.run(self.args)
                session.assert_not_called(); can.assert_not_called()
            setattr(self.args, flag, True)
        self.assertFalse(Path(self.args.output).exists())

    def test_manifest_mode_and_image_changes_are_rejected(self):
        image = bytearray(1024)
        entry = echo.pil.RAM + 513
        struct.pack_into("<II", image, 0, echo.pil.STACK_TOP, entry)
        c = dict(schema_version=1, mode=echo.MODE, external_can=True, expected_frames=16,
                 kernel_clock_nominal_hz=24000000, request_id=0x6E0, response_id=0x6E1,
                 load_address=echo.pil.RAM, mailbox_address=echo.pil.MAILBOX,
                 stack_bottom=echo.pil.STACK_BOTTOM, stack_top=echo.pil.STACK_TOP,
                 motor_output=False, flash_programming=False, entry=entry,
                 image_bytes=1024, image_sha256=echo.pil.sha(image))
        echo.validate(c, image)
        for key, val in (("mode", "can-internal-loopback"), ("external_can", False),
                         ("expected_frames", 17), ("motor_output", True),
                         ("request_id", 0x1B), ("kernel_clock_nominal_hz", 16000000)):
            with self.subTest(key=key), self.assertRaises(ValueError): echo.validate(dict(c, **{key: val}), image)
        image[-1] ^= 1
        with self.assertRaises(ValueError): echo.validate(c, image)

    def test_occupied_channel_unchanged(self):
        api = Api(); api.condition = 2
        with self.assertRaises(RuntimeError): echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        self.assertNotIn("preset", api.calls); self.assertNotIn("initialize", api.calls)

    def test_mode_preset_failure_prevents_initialization(self):
        api = Api(); api.status = 1
        with self.assertRaises(RuntimeError): echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        self.assertNotIn("initialize", api.calls)

    def test_post_initialize_wrong_mode_closes_channel(self):
        api = Api(); api.post_initialize_mode = 1
        with self.assertRaises(RuntimeError): echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        self.assertIn("close", api.calls); self.assertNotIn("write", api.calls)

    def test_unready_guest_never_transmits(self):
        api = Api(); bus = echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        with patch.object(echo, "verify_ready", side_effect=RuntimeError("Unready or PWM active")):
            with self.assertRaises(RuntimeError): bus.exchange(0, Mock())
        self.assertNotIn("write", api.calls); bus.close()

    def test_mode_changed_before_request_never_transmits(self):
        api = Api(); bus = echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1"); api.mode = 1
        with patch.object(echo, "verify_ready"):
            with self.assertRaises(RuntimeError): bus.exchange(0, Mock())
        self.assertNotIn("write", api.calls); bus.close()

    def test_frame_budget_and_mismatched_reply(self):
        api = Api(); bus = echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        for n in (-1, 16):
            with self.assertRaises(ValueError): bus.exchange(n, Mock())
        self.assertNotIn("write", api.calls)
        api.bad_reply = True
        with patch.object(echo, "verify_ready"):
            with self.assertRaises(RuntimeError): bus.exchange(0, Mock())
        self.assertEqual(api.calls.count("write"), 1); bus.close()

    def test_valid_reply_and_release(self):
        api = Api(); bus = echo.PcanEndpoint(api, BASIC, "PCAN_USBBUS1")
        with patch.object(echo, "verify_ready"):
            result = bus.exchange(15, Mock())
        self.assertEqual(result["sequence"], 15)
        self.assertEqual(api.reply.DATA[:4], [0x43, 0x41, 0x4E, 0x31])
        bus.close(); self.assertEqual(api.calls.count("close"), 1)


def main():
    global ROOT
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--output", required=True)
    args = p.parse_args(); ROOT = echo.pil.fresh_dir(args.output)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EchoTests))
    echo.pil.save_json(ROOT / "can-echo-contract-tests.json", dict(tests=result.testsRun,
        passed=result.wasSuccessful(), hardware_opened=False))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__": raise SystemExit(main())
