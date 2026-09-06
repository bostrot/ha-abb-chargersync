"""Binary charger protocol tunneled through the ChargerSync relay.

Plaintext frame layout (all multi-byte integers little-endian):

    offset  size  meaning
    0       1     start byte 0xFE (0xAA for cmd 0xBA/0xD9)
    1       1     command id
    2       1     0 in requests / result code in responses
    3       1     0
    4       2     payload length
    6       1     0
    7       1     XOR checksum of bytes 0..6, the 8 token bytes and the payload
    8       8     session token (all zeros before identity auth)
    16      n     payload
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
import time

CMD_SYNC_TIME = 0xB0
CMD_READ_SYS_INFO = 0xB1
CMD_SET_CHARGE_MODE = 0xB3
CMD_START_CHARGE = 0xB4
CMD_READ_STATUS = 0xB5
CMD_STOP_CHARGE = 0xB6
CMD_HISTORY_RECORDS = 0xB7
CMD_READ_TOTAL_CHARGE = 0xB8
CMD_POWER_CONTROL = 0xC0
CMD_QUERY_POWER_PERCENT = 0xE0
CMD_QUERY_CHARGE_MODE = 0xE6
CMD_IDENTITY_AUTH = 0xFE

START_BYTE = 0xFE
HEADER_LEN = 16
DES_KEY = b"ucserver"

RESPONSE_CODES = {
    0: "success",
    17: "parse error",
    18: "no permission",
    19: "service refused",
    20: "command does not exist",
    21: "command not supported",
    22: "token timeout",
    80: "device internal error",
    81: "command execution failed",
}
CODE_TOKEN_TIMEOUT = 22

STATUS_NAMES = {
    0x00: "idle",
    0x01: "plugged_in",
    0x02: "waiting_for_ev",
    0x03: "reserved",
    0x04: "suspended_evse",
    0x05: "suspended_ev",
    0x06: "charging",
    0x07: "paused",
    0x08: "charge_finished",
    0x0E: "unavailable",
    0x0F: "fault",
}


class ProtocolError(Exception):
    """Raised on malformed frames."""


def _des_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """DES/ECB/PKCS5; an 8-byte key makes TripleDES act as single DES."""
    pad = 8 - (len(data) % 8)
    data = data + bytes([pad]) * pad
    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    enc = Cipher(TripleDES(key), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


@dataclass
class Frame:
    """A parsed frame."""

    cmd: int
    code: int
    token: bytes
    payload: bytes
    start: int = START_BYTE

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def error(self) -> str:
        return RESPONSE_CODES.get(self.code, f"unknown error {self.code}")


def build_frame(cmd: int, payload: bytes | None, token: bytes) -> bytes:
    payload = payload or b""
    if len(token) != 8:
        raise ValueError("token must be 8 bytes")
    start = 0xAA if cmd in (0xBA, 0xD9) else START_BYTE
    hdr = bytearray([start, cmd & 0xFF, 0, 0, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF, 0])
    chk = 0
    for b in hdr:
        chk ^= b
    for b in token:
        chk ^= b
    for b in payload:
        chk ^= b
    return bytes(hdr) + bytes([chk]) + token + payload


def parse_frame(data: bytes) -> Frame:
    if len(data) < HEADER_LEN:
        raise ProtocolError("frame too short")
    if data[0] not in (START_BYTE, 0xAA):
        idx = max(data.find(b"\xfe"), data.find(b"\xaa"))
        if idx <= 0:
            raise ProtocolError("no start byte")
        data = data[idx:]
    cmd = data[1]
    code = data[2]
    body_len = data[4] | (data[5] << 8)
    if body_len > 1024:
        raise ProtocolError("body too long")
    total = HEADER_LEN + body_len
    if len(data) < total:
        raise ProtocolError("incomplete frame")
    data = data[:total]
    chk = 0
    for i, b in enumerate(data):
        if i != 7:
            chk ^= b
    if chk != data[7]:
        raise ProtocolError("checksum mismatch")
    return Frame(cmd=cmd, code=code, token=data[8:16], payload=data[16:], start=data[0])


def build_identity_auth(device_number: str, user_id: int, token: bytes) -> bytes:
    dn = device_number.replace("-", "")
    uid = str(user_id)
    blk = bytearray(48)
    blk[0 : len(dn)] = dn.encode("ascii")
    blk[20] = 2
    blk[21] = 1
    blk[22 : 22 + len(uid)] = uid.encode("ascii")
    enc = _des_ecb_encrypt(bytes(blk), DES_KEY)
    body = bytearray(130)
    body[0] = 0x80
    body[2 : 2 + len(enc)] = enc
    return build_frame(CMD_IDENTITY_AUTH, bytes(body), token)


def build_sync_time(token: bytes, utc_offset_hours: int = 0) -> bytes:
    payload = struct.pack("<I", int(time.time())) + bytes([(utc_offset_hours + 12) & 0xFF])
    return build_frame(CMD_SYNC_TIME, payload, token)


def build_read_status(token: bytes) -> bytes:
    return build_frame(CMD_READ_STATUS, b"\x00", token)


def build_query_sys_info(token: bytes) -> bytes:
    return build_frame(CMD_READ_SYS_INFO, None, token)


def build_start_charge(token: bytes) -> bytes:
    return build_frame(CMD_START_CHARGE, b"\x00\x00", token)


def build_stop_charge(token: bytes) -> bytes:
    return build_frame(CMD_STOP_CHARGE, b"\x00", token)


def build_query_power(token: bytes) -> bytes:
    return build_frame(CMD_QUERY_POWER_PERCENT, None, token)


def build_power_control(token: bytes, current_amps: int, port: int = 0) -> bytes:
    return build_frame(CMD_POWER_CONTROL, bytes([port & 0xFF, int(current_amps) & 0xFF]), token)


def build_query_total_energy(token: bytes) -> bytes:
    return build_frame(CMD_READ_TOTAL_CHARGE, None, token)


@dataclass
class IdentityAuthResult:
    success: bool
    token: bytes | None = None
    hardware_version: str = ""
    software_version: str = ""
    communication_version: str = ""


def parse_identity_auth(payload: bytes) -> IdentityAuthResult:
    if not payload:
        return IdentityAuthResult(False)
    if payload[0] == 0xFF:
        return IdentityAuthResult(False)
    res = IdentityAuthResult(True)
    if len(payload) >= 21:
        res.hardware_version = payload[1:21].rstrip(b"\x00").decode("ascii", "replace").replace("#", "")
    if len(payload) >= 24:
        res.software_version = f"{payload[23]}.{payload[22]}.{payload[21]}"
    if len(payload) >= 26:
        res.communication_version = f"{payload[24]}.{payload[25]}"
    if len(payload) >= 34:
        res.token = bytes(payload[26:34])
    else:
        res.success = False
    return res


@dataclass
class ChargerStatus:
    status_code: int = -1
    status: str = "unknown"
    phase_type: int = 0
    session_id: int = 0
    energy_kwh: float = 0.0
    voltage_l1: float = 0.0
    current_l1: float = 0.0
    voltage_l2: float = 0.0
    current_l2: float = 0.0
    voltage_l3: float = 0.0
    current_l3: float = 0.0
    duration_s: int = 0
    rated_current: int = 0
    fault_code: int = 0
    raw_extra: bytes = field(default=b"", repr=False)

    @property
    def power_w(self) -> float:
        return round(
            self.voltage_l1 * self.current_l1
            + self.voltage_l2 * self.current_l2
            + self.voltage_l3 * self.current_l3,
            1,
        )

    @property
    def charging(self) -> bool:
        return self.status_code == 0x06


def _u(b: bytes) -> int:
    return int.from_bytes(b, "little")


def parse_read_status(payload: bytes) -> ChargerStatus:
    st = ChargerStatus()
    if not payload:
        return st
    st.status_code = payload[0]
    st.status = STATUS_NAMES.get(payload[0], f"unknown_{payload[0]:02x}")
    rest = payload[1:]
    st.raw_extra = rest
    if st.status_code == 0x06 and len(rest) >= 1:
        st.phase_type = rest[0]
        if len(rest) >= 5:
            st.session_id = _u(rest[1:5])
        if len(rest) >= 7:
            st.energy_kwh = _u(rest[5:7]) / 100.0
        if len(rest) >= 11:
            st.voltage_l1 = _u(rest[7:11]) / 100.0
        if len(rest) >= 13:
            st.current_l1 = _u(rest[11:13]) / 100.0
        if st.phase_type == 0:
            if len(rest) >= 17:
                st.duration_s = _u(rest[13:17])
            if len(rest) >= 18:
                st.rated_current = rest[17]
        else:
            if len(rest) >= 17:
                st.voltage_l2 = _u(rest[13:17]) / 100.0
            if len(rest) >= 19:
                st.current_l2 = _u(rest[17:19]) / 100.0
            if len(rest) >= 23:
                st.voltage_l3 = _u(rest[19:23]) / 100.0
            if len(rest) >= 25:
                st.current_l3 = _u(rest[23:25]) / 100.0
            if len(rest) >= 29:
                st.duration_s = _u(rest[25:29])
            if len(rest) >= 30:
                st.rated_current = rest[29]
    elif st.status_code == 0x0F and len(rest) >= 2:
        st.fault_code = _u(rest[0:2])
    return st


@dataclass
class PowerControl:
    port: int = 0
    max_output_current: int = 0
    output_current: int = 0


def parse_power_control(payload: bytes) -> PowerControl:
    pc = PowerControl()
    if len(payload) >= 2:
        pc.port = payload[0]
        pc.max_output_current = payload[1]
    if len(payload) >= 3:
        pc.output_current = _u(payload[2:])
    return pc


@dataclass
class SysInfo:
    device_number: str = ""
    software_version: str = ""
    software_model: str = ""


def parse_sys_info(payload: bytes) -> SysInfo:
    si = SysInfo()
    if len(payload) >= 20:
        si.device_number = payload[0:20].rstrip(b"\x00").decode("ascii", "replace")
    if len(payload) >= 31:
        si.software_version = f"{payload[30]}.{payload[29]}.{payload[28]}"
    if len(payload) >= 51:
        si.software_model = payload[31:51].rstrip(b"\x00").decode("ascii", "replace")
    return si


def parse_simple_result(payload: bytes) -> int:
    return payload[0] if payload else 0
