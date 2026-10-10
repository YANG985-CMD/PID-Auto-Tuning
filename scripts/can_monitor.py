#!/usr/bin/env python3
"""Classic PCAN listen-only capture. No CAN Write/WriteFD/Reset calls.

Requires python-can's PCAN-Basic bindings and the PEAK driver/API library.
No target MCU access is performed. Raw frames are not TD3 experiences.
"""
import argparse
import json
import math
import sys
import time


def value(obj):
    return int(getattr(obj, "value", obj))


class ListenOnlyPcan:
    """Check the listen-only preset before Initialize, then read it back.

    Using PCAN-Basic directly lets us check every mode-setting return code.
    Occupied channels are rejected to avoid sharing with an active sender.
    """
    def __init__(self, api, basic, channel, bitrate):
        self.api, self.basic = api, basic
        self.initialized = False
        if channel not in basic.PCAN_CHANNEL_NAMES or not channel.startswith("PCAN_USBBUS"):
            raise RuntimeError("Only PCAN USB channels are supported")
        if bitrate not in basic.PCAN_BITRATES:
            raise RuntimeError("Unsupported classic CAN bitrate; no fallback is allowed")
        self.handle = basic.PCAN_CHANNEL_NAMES[channel]
        status, condition = api.GetValue(self.handle, basic.PCAN_CHANNEL_CONDITION)
        self.check(status, "channel query")
        if value(condition) != basic.PCAN_CHANNEL_AVAILABLE:
            raise RuntimeError("PCAN channel unavailable or occupied; close PCAN-View/other owners")
        # Refuse initialization unless the hardware preset succeeded.
        self.check(api.SetValue(self.handle, basic.PCAN_LISTEN_ONLY,
                                basic.PCAN_PARAMETER_ON), "listen-only preset")
        self.verify_mode()
        try:
            self.check(api.Initialize(self.handle, basic.PCAN_BITRATES[bitrate]), "initialize")
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
        self.check(status, "listen-only readback")
        if value(mode) != self.basic.PCAN_PARAMETER_ON:
            raise RuntimeError("PCAN listen-only readback is OFF; capture refused")

    def read(self):
        # Detect another client changing the shared mode while we are open.
        self.verify_mode()
        status, message, timestamp = self.api.Read(self.handle)
        if value(status) == value(self.basic.PCAN_ERROR_QRCVEMPTY):
            return None
        self.check(status, "receive")
        return describe(message, timestamp, self.basic)

    def close(self):
        if self.initialized:
            self.initialized = False
            self.check(self.api.Uninitialize(self.handle), "uninitialize")


def describe(message, timestamp, basic):
    flags, dlc = value(message.MSGTYPE), value(message.LEN)
    if not 0 <= dlc <= 8:
        raise RuntimeError("Invalid classic CAN DLC")
    remote = bool(flags & value(basic.PCAN_MESSAGE_RTR))
    data = b"" if remote else bytes(message.DATA[:dlc])
    return {
        "host_monotonic_s": time.monotonic(),
        # Adapter relative time, not MCU application time and not UTC.
        "adapter_timestamp_us": (value(timestamp.micros) + 1000 * value(timestamp.millis)
                                 + 1000 * (1 << 32) * value(timestamp.millis_overflow)),
        "arbitration_id": value(message.ID),
        "arbitration_id_hex": f"0x{value(message.ID):X}",
        "extended": bool(flags & value(basic.PCAN_MESSAGE_EXTENDED)),
        "remote": remote,
        "error": bool(flags & value(basic.PCAN_MESSAGE_ERRFRAME)),
        "status_frame": bool(flags & value(basic.PCAN_MESSAGE_STATUS)),
        "fd": bool(flags & value(basic.PCAN_MESSAGE_FD)),
        "dlc": dlc,
        "data_hex": data.hex(" "),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="PCAN_USBBUS1")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--duration", type=float, default=10.0,
                        help="listen seconds; 0 means until Ctrl+C")
    parser.add_argument("--probe", action="store_true",
                        help="query adapter capabilities without initializing a CAN channel")
    parser.add_argument("--allow-live", action="store_true",
                        help="explicitly open the adapter in hardware listen-only mode")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("duration must be finite and nonnegative")
    if not args.probe and not args.allow_live:
        parser.error("capture requires --allow-live; --probe does not initialize CAN")
    try:
        from can.interfaces.pcan import basic
        api = basic.PCANBasic()
    except (ImportError, OSError) as exc:
        print(f"PCAN dependency unavailable: {exc}; install requirements-can.txt and PCAN-Basic",
              file=sys.stderr)
        return 2
    try:
        if args.probe:
            status, channels = api.GetValue(basic.PCAN_NONEBUS, basic.PCAN_ATTACHED_CHANNELS)
            if value(status) != value(basic.PCAN_ERROR_OK):
                raise RuntimeError(f"PCAN adapter query failed: 0x{value(status):X}")
            print(json.dumps({"channel_initialized": False, "channels": [
                {"handle": value(c.channel_handle),
                 "name": c.device_name.decode("ascii", errors="replace"),
                 "supports_fd": bool(value(c.device_features) & basic.FEATURE_FD_CAPABLE),
                 "condition": value(c.channel_condition)} for c in channels]}))
            return 0
        bus = ListenOnlyPcan(api, basic, args.channel, args.bitrate)
        count, ids, error_frames = 0, set(), 0
        started = time.monotonic()
        try:
            while args.duration == 0 or time.monotonic() - started < args.duration:
                frame = bus.read()
                if frame is None:
                    time.sleep(.005)
                    continue
                count += 1
                ids.add((frame["arbitration_id_hex"], frame["extended"]))
                error_frames += int(frame["error"] or frame["status_frame"])
                print(json.dumps(frame, separators=(",", ":")), flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            bus.close()
        print(json.dumps({"listen_only_verified": True, "channel": args.channel,
                          "bitrate": args.bitrate, "duration_s": time.monotonic() - started,
                          "frames": count, "error_or_status_frames": error_frames,
                          "ids": sorted(ids), "td3_protocol_verified": False}), file=sys.stderr)
        return 0
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
