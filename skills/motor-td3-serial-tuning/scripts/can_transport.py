"""Classic CAN v1 codec and exclusive PCAN link. No hardware opened on import."""
import math
import struct
import time
import zlib

PROTOCOL = 'motor-td3-can-v1'
REQUEST_ID, RESPONSE_ID = 0x620, 0x621
MAX_PACKET, FRAGMENT_TIMEOUT = 192, .05
HEADER = struct.Struct('<BBHQQIQ')
TELEMETRY = struct.Struct('<QQIIB3x10f')
FLOATS = ('speed_ref', 'speed', 'error_history', 'integral_output', 'current',
          'vbus', 'temperature_c', 'kp', 'ki', 'elapsed_ms')
CAPABILITIES = ('atomic_gains', 'applied_feedback', 'lease', 'link_watchdog',
                'fault_latch', 'single_owner')
TYPES = {'hello': 1, 'begin': 2, 'gains': 3, 'stop': 4, 'hello_reply': 0x81, 'telemetry': 0x82}


class WireError(RuntimeError):
    pass


def ident(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 64
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.' for c in value)):
        raise WireError('CAN identifiers require 1..64 ASCII letters/digits/-_.')
    return bytes([len(value)]) + value.encode('ascii')


def take_ident(body, at):
    if at >= len(body) or at + 1 + body[at] > len(body):
        raise WireError('Incomplete identity')
    end = at + 1 + body[at]
    try:
        name = body[at+1:end].decode('ascii')
    except UnicodeError as exc:
        raise WireError('Non-ASCII identity') from exc
    ident(name)
    return name, end


def pack(obj, nonce, boot=0, wire_seq=0, expires_us=0):
    """A datagram uses fixed little-endian integers/IEEE float32 and IEEE CRC32."""
    op = obj.get('type')
    if op not in TYPES or not 0 < nonce < 2**64 or not 0 <= boot < 2**64:
        raise WireError('Invalid type/session/boot')
    if not 0 <= wire_seq < 2**32 or not 0 <= expires_us < 2**64:
        raise WireError('Sequence/time overflow')
    if op == 'hello':
        if set(obj) != {'type', 'profile_id'} or boot or wire_seq or expires_us:
            raise WireError('Invalid hello fields')
        body = ident(obj['profile_id'])
    elif op == 'hello_reply':
        bits = sum(1 << CAPABILITIES.index(c) for c in set(obj['capabilities']))
        body = struct.pack('<H', bits) + ident(obj['firmware_id']) + ident(obj['profile_id'])
    elif op == 'begin':
        if set(obj) != {'type', 'profile_id', 'speed_ref', 'lease_ms'}:
            raise WireError('Invalid begin fields')
        ident(obj['profile_id'])
        body = struct.pack('<fI', obj['speed_ref'], obj['lease_ms'])
    elif op == 'gains':
        if set(obj) != {'type', 'command_seq', 'kp', 'ki', 'lease_ms'}:
            raise WireError('Invalid gain fields')
        body = struct.pack('<IffI', obj['command_seq'], obj['kp'], obj['ki'], obj['lease_ms'])
    elif op == 'stop':
        if set(obj) != {'type'}:
            raise WireError('Invalid stop fields')
        body = b''
    else:
        body = TELEMETRY.pack(obj['t_us'], obj['t_apply_us'], obj['applied_seq'],
                              obj['fault'], obj['enabled'], *(obj[k] for k in FLOATS))
    data = HEADER.pack(1, TYPES[op], 0, nonce, boot, wire_seq, expires_us) + body
    data += struct.pack('<I', zlib.crc32(data))
    unpack(data)  # Reject non-finite/invalid numeric values before any transmission.
    return data


def unpack(data, *, allow_missing_temperature=False):
    if (not 36 <= len(data) <= MAX_PACKET
            or zlib.crc32(data[:-4]) != struct.unpack('<I', data[-4:])[0]):
        raise WireError('CAN datagram size/CRC failure')
    version, kind, reserved, nonce, boot, wire_seq, expires = HEADER.unpack_from(data)
    if version != 1 or reserved or not nonce or kind not in TYPES.values():
        raise WireError('Unsupported CAN header')
    body = data[HEADER.size:-4]
    meta = dict(nonce=nonce, boot=boot, wire_seq=wire_seq, expires_us=expires)
    if kind == 1:
        name, end = take_ident(body, 0)
        if end != len(body) or boot or wire_seq or expires:
            raise WireError('Invalid hello request')
        obj = dict(type='hello', profile_id=name)
    elif kind == 0x81:
        if len(body) < 4 or not boot or wire_seq or expires:
            raise WireError('Invalid hello reply')
        flags = struct.unpack_from('<H', body)[0]
        if flags & ~63:
            raise WireError('Unknown capability flags')
        firmware, at = take_ident(body, 2)
        profile, at = take_ident(body, at)
        if at != len(body):
            raise WireError('Trailing hello bytes')
        obj = dict(type='hello', protocol_id=PROTOCOL, firmware_id=firmware,
                   profile_id=profile, boot_id=f'{boot:016x}',
                   capabilities=[c for i, c in enumerate(CAPABILITIES) if flags & (1 << i)])
    elif kind in (2, 3, 4):
        if not boot or not wire_seq or (kind != 4 and not expires):
            raise WireError('Command requires boot/sequence/deadline')
        expected = {2: 8, 3: 16, 4: 0}[kind]
        if len(body) != expected:
            raise WireError('Invalid command size')
        obj = dict(type={2: 'begin', 3: 'gains', 4: 'stop'}[kind])
        if kind == 2:
            obj['speed_ref'], obj['lease_ms'] = struct.unpack('<fI', body)
        elif kind == 3:
            obj['command_seq'], obj['kp'], obj['ki'], obj['lease_ms'] = struct.unpack('<IffI', body)
            if not obj['command_seq']:
                raise WireError('Zero applied-command sequence')
        if kind != 4 and not 1 <= obj['lease_ms'] <= 4294967:
            raise WireError('Invalid lease')
    else:
        if len(body) != TELEMETRY.size or not boot or expires or body[24] not in (0, 1) or any(body[25:28]):
            raise WireError('Invalid telemetry size/flags')
        values = TELEMETRY.unpack(body)
        obj = dict(type='telemetry', boot_id=f'{boot:016x}', seq=wire_seq,
                   t_us=values[0], t_apply_us=values[1], applied_seq=values[2],
                   fault=values[3], enabled=bool(values[4]), **dict(zip(FLOATS, values[5:])))
        if obj['t_apply_us'] > obj['t_us']:
            raise WireError('Telemetry apply time after snapshot')
    if (allow_missing_temperature and obj.get('type') == 'telemetry'
            and math.isnan(obj['temperature_c'])):
        obj['temperature_c'] = None
    if any(isinstance(v, float) and not math.isfinite(v) for v in obj.values()):
        raise WireError('Non-finite CAN value')
    return obj, meta


def fragment(data, transfer):
    unpack(data)
    if not 0 <= transfer <= 255:
        raise WireError('Invalid fragment transfer counter')
    return [bytes([0xD1, transfer, i // 4, len(data)]) + data[i:i+4].ljust(4, b'\0')
            for i in range(0, len(data), 4)]


class Reassembler:
    def __init__(self, *, allow_missing_temperature=False):
        self.pending = None
        self.last_time = 0
        self.allow_missing_temperature = allow_missing_temperature

    def check_timeout(self, now):
        if now < self.last_time or (self.pending is not None and now - self.started >= FRAGMENT_TIMEOUT):
            self.pending = None
            raise WireError('Fragment timeout/clock reversal')
        self.last_time = now

    def feed(self, frame, now):
        self.check_timeout(now)
        if len(frame) != 8 or frame[0] != 0xD1 or not 36 <= frame[3] <= MAX_PACKET:
            raise WireError('Invalid classic CAN fragment')
        tag, index, size = frame[1:4]
        if self.pending is None:
            if index:
                raise WireError('Missing first fragment')
            self.pending, self.started, self.tag, self.size, self.index = bytearray(), now, tag, size, 0
        if (tag, size, index) != (self.tag, self.size, self.index):
            self.pending = None
            raise WireError('Fragment gap/reorder/overlap')
        count = min(4, size - len(self.pending))
        if any(frame[4+count:]):
            self.pending = None
            raise WireError('Nonzero fragment padding')
        self.pending.extend(frame[4:4+count])
        self.index += 1
        if len(self.pending) == size:
            result, self.pending = bytes(self.pending), None
            unpack(result, allow_missing_temperature=self.allow_missing_temperature)
            return result
        return None


class PcanLink:
    """Single available PCAN-USB channel, normal mode, fixed classic identifiers."""
    def __init__(self, channel, api=None, basic=None):
        if basic is None:
            from can.interfaces.pcan import basic
        self.basic = basic
        self.api = api if api is not None else basic.PCANBasic()
        self.initialized = False
        if channel not in basic.PCAN_CHANNEL_NAMES or not channel.startswith('PCAN_USBBUS'):
            raise WireError('Expected a classic PCAN USB channel')
        self.handle = basic.PCAN_CHANNEL_NAMES[channel]
        status, condition = self.api.GetValue(self.handle, basic.PCAN_CHANNEL_CONDITION)
        self.check(status)
        if self.value(condition) != self.value(basic.PCAN_CHANNEL_AVAILABLE):
            raise WireError('CAN channel occupied/unavailable')
        self.check(self.api.SetValue(self.handle, basic.PCAN_LISTEN_ONLY, basic.PCAN_PARAMETER_OFF))
        self.mode()
        try:
            self.check(self.api.Initialize(self.handle, basic.PCAN_BITRATES[500000]))
            self.initialized = True
            self.mode()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def value(value):
        return int(getattr(value, 'value', value))

    def check(self, status):
        if self.value(status) != self.value(self.basic.PCAN_ERROR_OK):
            raise WireError(f'PCAN driver error 0x{self.value(status):X}')

    def mode(self):
        status, mode = self.api.GetValue(self.handle, self.basic.PCAN_LISTEN_ONLY)
        self.check(status)
        if self.value(mode) != self.value(self.basic.PCAN_PARAMETER_OFF):
            raise WireError('PCAN normal mode readback failed')

    def send(self, data):
        if len(data) != 8 or data[0] != 0xD1:
            raise WireError('Only CAN v1 fragments may be transmitted')
        self.mode()
        message = self.basic.TPCANMsg()
        message.ID, message.MSGTYPE, message.LEN = REQUEST_ID, self.basic.PCAN_MESSAGE_STANDARD, 8
        message.DATA[:8] = data
        self.check(self.api.Write(self.handle, message))

    def receive(self):
        self.mode()
        status, message, stamp = self.api.Read(self.handle)
        if self.value(status) == self.value(self.basic.PCAN_ERROR_QRCVEMPTY):
            time.sleep(.001)
            return None
        self.check(status)
        flags = self.value(message.MSGTYPE)
        if flags != self.value(self.basic.PCAN_MESSAGE_STANDARD):
            raise WireError('Unexpected remote/extended/error/status frame')
        if self.value(message.ID) != RESPONSE_ID:
            return None
        if self.value(message.LEN) != 8:
            raise WireError('Wrong CAN fragment DLC')
        return bytes(message.DATA[:8])

    def close(self):
        if self.initialized:
            self.initialized = False
            self.check(self.api.Uninitialize(self.handle))
