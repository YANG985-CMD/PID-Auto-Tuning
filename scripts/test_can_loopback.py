#!/usr/bin/env python3
"""Offline safety contract checks; never open a debug probe."""
import argparse
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import stm32_can_loopback as diag

ROOT = None


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / self._testMethodName
        self.source = self.root / "build"
        self.source.mkdir(parents=True)
        self.image = bytearray(1024)
        entry = diag.pil.RAM + 513
        struct.pack_into("<II", self.image, 0, diag.pil.STACK_TOP, entry)
        self.contract = dict(schema_version=1, mode=diag.MODE, load_address=diag.pil.RAM,
                             mailbox_address=diag.pil.MAILBOX, stack_bottom=diag.pil.STACK_BOTTOM,
                             stack_top=diag.pil.STACK_TOP, entry=entry, image_bytes=len(self.image),
                             image_sha256=diag.pil.sha(self.image), expected_frames=64,
                             external_can=False, motor_output=False, flash_programming=False)
        self.args = SimpleNamespace(build=str(self.source), output=str(self.root / "result"),
                                    power_stage_disconnected=True, reset_and_halt_ack=True)

    def refuse(self):
        (self.source / "can-loopback.bin").write_bytes(self.image)
        diag.pil.save_json(self.source / "can-build.json", self.contract)
        with patch.object(diag.pil, "session", side_effect=AssertionError("No hardware allowed")) as connect:
            with self.assertRaises(ValueError):
                diag.run(self.args)
            connect.assert_not_called()
        self.assertFalse((self.root / "result").exists())

    def test_missing_power_confirmation(self):
        self.args.power_stage_disconnected = False
        self.refuse()

    def test_missing_reset_acknowledgement(self):
        self.args.reset_and_halt_ack = False
        self.refuse()

    def test_external_mode_or_side_effect_is_rejected(self):
        for key, value in (("mode", "can-external-loopback"), ("external_can", True),
                           ("motor_output", True), ("flash_programming", True)):
            with self.subTest(key=key):
                old = self.contract[key]
                self.contract[key] = value
                self.refuse()
                self.contract[key] = old

    def test_modified_image(self):
        self.image[-1] ^= 0x80
        self.refuse()

    def test_entry_in_flash_with_matching_digest(self):
        self.contract["entry"] = diag.pil.FLASH + 1
        struct.pack_into("<I", self.image, 4, self.contract["entry"])
        self.contract["image_sha256"] = diag.pil.sha(self.image)
        self.refuse()

    def test_entry_outside_image(self):
        self.contract["entry"] = diag.pil.CODE_LIMIT - 1
        struct.pack_into("<I", self.image, 4, self.contract["entry"])
        self.contract["image_sha256"] = diag.pil.sha(self.image)
        self.refuse()

    def test_oversized_image(self):
        self.image.extend(bytes(diag.pil.CODE_LIMIT - diag.pil.RAM))
        self.contract.update(image_bytes=len(self.image), image_sha256=diag.pil.sha(self.image))
        self.refuse()

    def test_mailbox_or_stack_relocation(self):
        for key in ("mailbox_address", "stack_bottom", "stack_top"):
            with self.subTest(key=key):
                self.contract[key] += 16
                self.refuse()
                self.contract[key] -= 16

    def test_unbounded_case_count(self):
        self.contract["expected_frames"] = 100000
        self.refuse()

    def fake_session_run(self, identity_error=False):
        (self.source / "can-loopback.bin").write_bytes(self.image)
        diag.pil.save_json(self.source / "can-build.json", self.contract)
        target = Mock()
        target.get_state.return_value = "HALTED"
        target.read32.return_value = 0
        # Force an early memory-read failure after a valid identity.
        target.read_memory_block8.side_effect = RuntimeError("Injected debug read failure")
        session = Mock(target=target)
        api = SimpleNamespace(State=SimpleNamespace(HALTED="HALTED", RUNNING="RUNNING"),
                              ResetType=SimpleNamespace(SYSRESETREQ="SYSRESETREQ"))
        modules = {"pyocd.core.target": SimpleNamespace(Target=api)}
        with patch.dict("sys.modules", modules), patch.object(diag.pil, "session", return_value=session), \
                patch.object(diag.pil, "identity", side_effect=ValueError("Unsupported chip")
                             if identity_error else None, return_value={"flash_kb": 128}):
            result = diag.run(self.args)
        session.close.assert_called_once()
        self.assertFalse(result["internal_loopback_verified"])
        target.resume.assert_not_called()
        return target

    def test_wrong_target_does_not_reset_or_halt(self):
        target = self.fake_session_run(identity_error=True)
        target.halt.assert_not_called()
        target.reset_and_halt.assert_not_called()
        target.write_memory_block8.assert_not_called()

    def test_debug_read_failure_cleans_up_without_running_guest(self):
        target = self.fake_session_run()
        target.halt.assert_called_once()
        target.reset_and_halt.assert_called_once()
        target.write_memory_block8.assert_not_called()

    def test_report_rejects_wrong_data_mode_or_output(self):
        r = dict.fromkeys(diag.FIELDS, 0)
        r.update(magic=0x43414E31, schema=1, state=2, expected=64, received=64,
                 standard=32, extended=32, dlc_mask=0x1FF, cccr=0xE0, test=0x10,
                 nbtp=0x10904, cycles=10000, rcc_cfgr=5, rcc_ccipr=0x02000000)

        def data():
            return struct.pack("<" + "I" * len(diag.FIELDS), *(r[k] for k in diag.FIELDS))

        self.assertEqual(diag.analyze(data())["received"], 64)
        for key, value in (("received", 63), ("extended", 31), ("dlc_mask", 0xFF),
                           ("cccr", 0x80), ("test", 0), ("error", 8), ("state", 1),
                           ("tim1_bdtr", 0x8000), ("gpio_clock", 1), ("txbrp", 1),
                           ("ecr", 1), ("psr", 3), ("cycles", 0)):
            with self.subTest(key=key):
                old = r[key]
                r[key] = value
                with self.assertRaises(ValueError):
                    diag.analyze(data())
                r[key] = old
        with self.assertRaises(ValueError):
            diag.analyze(data()[:-1])


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    ROOT = diag.pil.fresh_dir(args.output)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    diag.pil.save_json(ROOT / "can-contract-tests.json", dict(tests=result.testsRun,
                      passed=result.wasSuccessful(), hardware_opened=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
