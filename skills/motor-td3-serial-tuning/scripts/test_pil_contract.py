#!/usr/bin/env python3
"""Reject unsafe/mismatched PIL requests without opening a debug probe."""
import argparse
import json
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import stm32_actor_pil as pil

ROOT = None


class PilContractTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / self._testMethodName
        self.root.mkdir(parents=True)
        self.source = self.root / "build"
        self.source.mkdir()
        self.image = bytearray(1024)
        struct.pack_into("<II", self.image, 0, pil.STACK_TOP, pil.RAM + 513)
        rows = [{"raw_state": [0.0] * 10, "action": [0.0, 0.0], "gains": [0.0, 0.0]}]
        pil.save_json(self.source / "reference.json", rows)
        self.contract = dict(load_address=pil.RAM, mailbox_address=pil.MAILBOX,
                             stack_bottom=pil.STACK_BOTTOM, stack_top=pil.STACK_TOP,
                             image_sha256=pil.sha(self.image), entry=pil.RAM + 513,
                             reference_sha256=pil.sha((self.source / "reference.json").read_bytes()),
                             vectors=1)
        self.args = SimpleNamespace(power_stage_disconnected=True, reset_and_halt_ack=True,
                                    build=str(self.source), output=str(self.root / "result"))

    def refuse(self):
        (self.source / "actor-pil.bin").write_bytes(self.image)
        pil.save_json(self.source / "pil-build.json", self.contract)
        with patch.object(pil, "session", side_effect=AssertionError("Must not connect a probe")) as connect:
            with self.assertRaises(ValueError):
                pil.run(self.args)
            connect.assert_not_called()
        self.assertFalse((self.root / "result").exists())

    def test_requires_physical_power_confirmation(self):
        self.args.power_stage_disconnected = False
        self.refuse()

    def test_requires_reset_acknowledgement(self):
        self.args.reset_and_halt_ack = False
        self.refuse()

    def test_modified_image_is_rejected(self):
        self.image[-1] ^= 1
        self.refuse()

    def test_entry_in_flash_is_rejected_even_with_matching_hash(self):
        self.contract["entry"] = pil.FLASH + 1
        struct.pack_into("<I", self.image, 4, self.contract["entry"])
        self.contract["image_sha256"] = pil.sha(self.image)
        self.refuse()

    def test_entry_outside_loaded_image_is_rejected(self):
        self.contract["entry"] = pil.CODE_LIMIT - 1
        struct.pack_into("<I", self.image, 4, self.contract["entry"])
        self.contract["image_sha256"] = pil.sha(self.image)
        self.refuse()

    def test_stack_relocation_is_rejected(self):
        self.contract["stack_top"] += 1024
        self.refuse()

    def test_modified_reference_is_rejected(self):
        text = (self.source / "reference.json").read_text()
        (self.source / "reference.json").write_text(text + " ", encoding="utf-8")
        self.refuse()

    def test_oversized_image_is_rejected(self):
        self.image.extend(bytes(pil.CODE_LIMIT - pil.RAM))
        self.contract["image_sha256"] = pil.sha(self.image)
        self.refuse()

    def test_wrong_chip_or_capacity_is_rejected(self):
        class Chip:
            def __init__(self, cpu=0x410FC241, device=0x20036468, capacity=128):
                self.cpu, self.device, self.capacity = cpu, device, capacity
            def read32(self, address):
                return self.cpu if address == 0xE000ED00 else self.device
            def read16(self, address):
                return self.capacity
        self.assertEqual(pil.identity(Chip())["flash_kb"], 128)
        for chip in (Chip(cpu=0x410CC200), Chip(device=0x20036469), Chip(capacity=256)):
            with self.assertRaises(ValueError):
                pil.identity(chip)


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    ROOT = pil.fresh_dir(args.output)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PilContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    pil.save_json(ROOT / "pil-contract-tests.json", dict(tests=result.testsRun,
                  passed=result.wasSuccessful(), hardware_accessed=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
