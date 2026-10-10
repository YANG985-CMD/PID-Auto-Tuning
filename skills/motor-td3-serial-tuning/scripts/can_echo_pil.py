#!/usr/bin/env python3
"""Bounded PCAN <-> STM32G431 CAN-only SRAM echo diagnostic.

This is an active communication test, not Listen-Only capture. The board must
have confirmed logic supply and the motor output must remain disabled. Only
16 diagnostic frames are sent, after SRAM readback and guest readiness checks.
No start/stop/gain commands, original application resume or Flash programming.
"""
import argparse
import json
import struct
import time
from pathlib import Path
import can_loopback_pil as diag

pil = diag.pil
MODE = "can-external-echo"
FIELDS = ("magic schema state error expected received sent cccr test nbtp psr ecr "
          "cycles rcc_cr rcc_cfgr tim1_cr1 tim1_ccer tim1_bdtr phase_modes gpio_clocks last0 last1").split()


def build(args):
    out, contract, data = diag.compile_guest(args, "can_echo", "can_echo_entry", MODE, 16, True)
    contract.update(kernel_clock_nominal_hz=24000000, request_id=0x6E0, response_id=0x6E1)
    validate(contract, data)
    (out / "can-echo.bin").write_bytes(data)
    pil.save_json(out / "can-build.json", contract)
    return contract


def validate(c, image):
    # Reuse the SRAM range/entry/hash contract, keeping modes distinct.
    if (c.get("mode") != MODE or c.get("external_can") is not True or c.get("expected_frames") != 16
            or c.get("kernel_clock_nominal_hz") != 24000000
            or (c.get("request_id"), c.get("response_id")) != (0x6E0, 0x6E1)):
        raise ValueError("Invalid CAN-only external echo contract")
    internal = dict(c, mode=diag.MODE, external_can=False, expected_frames=64)
    diag.validate_image(internal, image)


def value(x):
    return int(getattr(x, "value", x))


class PcanEndpoint:
    """Own an available classic PCAN channel in normal mode; no reset calls."""
    def __init__(self, api, basic, channel):
        self.api, self.basic, self.initialized = api, basic, False
        if channel not in basic.PCAN_CHANNEL_NAMES or not channel.startswith("PCAN_USBBUS"):
            raise ValueError("Expected a PCAN USB channel")
        self.handle = basic.PCAN_CHANNEL_NAMES[channel]
        status, condition = api.GetValue(self.handle, basic.PCAN_CHANNEL_CONDITION)
        self.check(status, "channel query")
        if value(condition) != basic.PCAN_CHANNEL_AVAILABLE:
            raise RuntimeError("PCAN channel occupied/unavailable; no shared writer permitted")
        self.check(api.SetValue(self.handle, basic.PCAN_LISTEN_ONLY, basic.PCAN_PARAMETER_OFF), "normal preset")
        self.verify_mode()
        try:
            self.check(api.Initialize(self.handle, basic.PCAN_BITRATES[500000]), "initialize")
            self.initialized = True
            self.verify_mode()
        except BaseException:
            self.close()
            raise

    def check(self, status, operation):
        if value(status) != value(self.basic.PCAN_ERROR_OK):
            raise RuntimeError(f"PCAN {operation} failed: 0x{value(status):X}")

    def verify_mode(self):
        status, mode = self.api.GetValue(self.handle, self.basic.PCAN_LISTEN_ONLY)
        self.check(status, "mode readback")
        if value(mode) != self.basic.PCAN_PARAMETER_OFF:
            raise RuntimeError("PCAN must be in verified normal mode to acknowledge the board")

    def exchange(self, n, target):
        if not 0 <= n < 16:
            raise ValueError("Diagnostic frame budget exceeded")
        verify_ready(target)  # Never send to an unknown or restored Flash application.
        self.verify_mode()
        message = self.basic.TPCANMsg()
        message.ID, message.MSGTYPE, message.LEN = 0x6E0, self.basic.PCAN_MESSAGE_STANDARD, 8
        payload = bytes([0x43, 0x41, 0x4E, 0x31, n, n ^ 0xFF, n ^ 0xA5, 0x5A])
        message.DATA[:8] = payload
        self.check(self.api.Write(self.handle, message), "diagnostic request")
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            self.verify_mode()
            status, received, timestamp = self.api.Read(self.handle)
            if value(status) == value(self.basic.PCAN_ERROR_QRCVEMPTY):
                time.sleep(0.002)
                continue
            self.check(status, "receive")
            if value(received.MSGTYPE) != value(self.basic.PCAN_MESSAGE_STANDARD):
                raise RuntimeError("Unexpected CAN error/status/extended/remote frame")
            if value(received.ID) != 0x6E1:
                continue
            if value(received.LEN) != 8 or bytes(received.DATA[:8]) != payload:
                raise RuntimeError("Diagnostic reply payload/sequence mismatch")
            return dict(sequence=n, payload_hex=payload.hex(" "))
        raise RuntimeError("CAN echo timeout: inspect board supply, termination, wiring and ACK")

    def close(self):
        if self.initialized:
            self.initialized = False
            self.check(self.api.Uninitialize(self.handle), "uninitialize")


def verify_ready(target):
    from pyocd.core.target import Target
    head = struct.unpack("<6I", bytes(target.read_memory_block8(pil.MAILBOX, 24)))
    if (head[:5] != (0x434E4531, 1, 1, 0, 16) or target.get_state() != Target.State.RUNNING
            or any(target.read32(a) for a in (0x40012C00, 0x40012C20, 0x40012C44))
            or target.read32(0x4002104C) != 1
            or target.read32(0x48000000) & 0x003F0000 != 0x003F0000
            or target.read32(0x40006418) & 0x1A1
            or target.read32(0x40006410) & 0x10
            or target.read32(0x4000641C) != 0x20904):
        raise RuntimeError("CAN-only guest not ready, wrong mode, or PWM/phase pins not disabled")


def analyze(data):
    if len(data) != 4 * len(FIELDS):
        raise ValueError("Incomplete CAN echo mailbox")
    r = dict(zip(FIELDS, struct.unpack("<" + "I" * len(FIELDS), data)))
    if (tuple(r[k] for k in ("magic", "schema", "state", "error", "expected", "received", "sent"))
            != (0x434E4531, 1, 2, 0, 16, 16, 16)
            or r["cccr"] & 0x1A1 or r["test"] & 0x10 or r["nbtp"] != 0x20904
            or r["ecr"] & 0xFFFF or r["psr"] & 0xE7
            or any(r[k] for k in ("tim1_cr1", "tim1_ccer", "tim1_bdtr"))
            or r["phase_modes"] != 0x003F0000 or r["gpio_clocks"] != 1
            or not r["rcc_cr"] & (1 << 17) or r["rcc_cfgr"] & 0x7FC != 4
            or not 0 < r["cycles"] < 128000000):
        raise ValueError("CAN echo completion/data/normal-mode/PWM check failed: " + str(r))
    return r


def run(args):
    if not args.allow_live or not args.board_supply_confirmed or not args.motor_output_disabled_ack:
        raise ValueError("Requires authorized active CAN test, confirmed board supply and disabled motor output")
    source = Path(args.build).resolve()
    contract = json.loads((source / "can-build.json").read_text(encoding="utf-8"))
    image = (source / "can-echo.bin").read_bytes()
    validate(contract, image)
    out = pil.fresh_dir(args.output)
    from pyocd.core.target import Target
    session = pil.session(out)
    target, before, endpoint, supported = None, None, None, False
    report = dict(schema_version=1, mode=MODE, external_can_link_verified=False,
                  motor_output=False, flash_programming=False, original_application_resumed=False,
                  board_supply_confirmed_by_user=True, diagnostic_request_limit=16)
    try:
        session.open()
        target = session.target
        report["identity"] = pil.identity(target)
        supported = True
        target.halt()
        if target.get_state() != Target.State.HALTED:
            raise RuntimeError("Could not halt MCU")
        before = bytes(target.read_memory_block8(pil.FLASH, pil.FLASH_BYTES))
        target.reset_and_halt(Target.ResetType.SYSRESETREQ)
        if target.get_state() != Target.State.HALTED or any(diag.safe_registers(target).values()):
            raise RuntimeError("Post-reset PWM/GPIO prerequisite failed")
        target.write_memory_block8(pil.RAM, bytes(pil.STACK_TOP - pil.RAM))
        target.write_memory_block8(pil.RAM, image)
        target.write_memory_block8(pil.STACK_BOTTOM, bytes([0xA5]) * (pil.STACK_TOP - pil.STACK_BOTTOM))
        if bytes(target.read_memory_block8(pil.RAM, len(image))) != image:
            raise RuntimeError("SRAM image readback failed")
        # Only after the supported MCU is paused with a verified image, open an active CAN node.
        from can.interfaces.pcan import basic
        endpoint = PcanEndpoint(basic.PCANBasic(), basic, args.channel)
        target.selected_core.write_core_registers_raw(
            ["msp", "psp", "control", "primask", "basepri", "faultmask", "xpsr", "pc"],
            [pil.STACK_TOP, pil.STACK_TOP, 0, 1, 0, 0, 0x01000000, contract["entry"]])
        target.write32(0xE000ED08, pil.RAM)
        target.resume()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            head = struct.unpack("<4I", bytes(target.read_memory_block8(pil.MAILBOX, 16)))
            if head == (0x434E4531, 1, 1, 0): break
            if target.get_state() != Target.State.RUNNING: break
            time.sleep(0.005)
        report["exchanges"] = []
        for n in range(16):
            report["exchanges"].append(endpoint.exchange(n, target))
        deadline = time.monotonic() + 0.5
        while target.get_state() == Target.State.RUNNING and time.monotonic() < deadline:
            time.sleep(0.005)
        target.halt()
        data = bytes(target.read_memory_block8(pil.MAILBOX, 4 * len(FIELDS)))
        pil.save_json(out / "mailbox.json", dict(zip(FIELDS, struct.unpack("<" + "I" * len(FIELDS), data))))
        report["mailbox"] = analyze(data)
        paint = bytes(target.read_memory_block8(pil.STACK_BOTTOM, pil.STACK_TOP - pil.STACK_BOTTOM))
        report["stack_bottom_fence_intact"] = paint[:64] == bytes([0xA5]) * 64
        if not report["stack_bottom_fence_intact"] or any(diag.safe_registers(target).values()):
            raise RuntimeError("CAN echo stack/PWM/cleanup check failed")
        report.update(external_can_link_verified=True, classic_can=True, bitrate=500000,
                      kernel_clock_nominal_hz=24000000, image_bytes=len(image), image_sha256=pil.sha(image))
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if target is not None and supported:
            try:
                target.reset_and_halt(Target.ResetType.SYSRESETREQ)
                report["core_left_halted"] = target.get_state() == Target.State.HALTED
                report["final_registers"] = diag.safe_registers(target)
                if before is not None:
                    report["flash_unchanged"] = bytes(target.read_memory_block8(pil.FLASH, pil.FLASH_BYTES)) == before
                if (not report["core_left_halted"] or any(report["final_registers"].values())
                        or report.get("flash_unchanged") is not True):
                    report["external_can_link_verified"] = False
                    report.setdefault("error", "Final reset/halt/PWM/Flash check failed")
            except Exception as exc:
                report["external_can_link_verified"] = False
                report["cleanup_error"] = str(exc)
        if endpoint is not None:
            try:
                endpoint.close()
                report["adapter_released"] = True
            except Exception as exc:
                report["external_can_link_verified"] = False
                report["adapter_cleanup_error"] = str(exc)
        try:
            session.close()
        except Exception as exc:
            report["external_can_link_verified"] = False
            report["disconnect_error"] = str(exc)
        pil.save_json(out / "can-result.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_subparsers(dest="mode", required=True)
    b = modes.add_parser("build")
    b.add_argument("--arm-bin", required=True); b.add_argument("--cmsis-root", required=True)
    b.add_argument("--output", required=True)
    r = modes.add_parser("run")
    r.add_argument("--build", required=True); r.add_argument("--output", required=True)
    r.add_argument("--channel", default="PCAN_USBBUS1")
    r.add_argument("--allow-live", action="store_true")
    r.add_argument("--board-supply-confirmed", action="store_true")
    r.add_argument("--motor-output-disabled-ack", action="store_true")
    args = p.parse_args()
    result = build(args) if args.mode == "build" else run(args)
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.mode == "run" and not result["external_can_link_verified"]: raise SystemExit(1)

if __name__ == "__main__": main()
