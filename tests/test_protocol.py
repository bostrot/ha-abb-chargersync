import struct
from datetime import time

import pytest

from custom_components.abb_chargersync import protocol as p

TOKEN = bytes.fromhex("F94734D26AC0F1D1")


def test_build_frame_layout_and_checksum():
    frame = p.build_frame(p.CMD_READ_STATUS, b"\x00", TOKEN)
    assert frame.hex().upper() == "FEB5000001000098F94734D26AC0F1D100"
    assert frame[0] == p.START_BYTE
    assert frame[1] == p.CMD_READ_STATUS
    assert frame[4] | (frame[5] << 8) == 1
    assert frame[8:16] == TOKEN


def test_build_frame_uses_aa_start_for_upgrade_commands():
    assert p.build_frame(0xBA, b"", bytes(8))[0] == 0xAA
    assert p.build_frame(0xD9, b"", bytes(8))[0] == 0xAA


def test_build_frame_rejects_bad_token():
    with pytest.raises(ValueError):
        p.build_frame(p.CMD_READ_STATUS, b"", bytes(4))


def test_parse_frame_roundtrip():
    frame = p.parse_frame(bytes.fromhex("AAB50000020000CEF94734D26AC0F1D10001"))
    assert frame.cmd == p.CMD_READ_STATUS
    assert frame.ok
    assert frame.token == TOKEN
    assert frame.payload == b"\x00\x01"


def test_parse_frame_resyncs_on_leading_garbage():
    raw = b"\x00\x11" + bytes.fromhex("AAB50000020000CEF94734D26AC0F1D10001")
    assert p.parse_frame(raw).cmd == p.CMD_READ_STATUS


def test_parse_frame_checksum_mismatch():
    raw = bytearray(bytes.fromhex("AAB50000020000CEF94734D26AC0F1D10001"))
    raw[-1] ^= 0xFF
    with pytest.raises(p.ProtocolError):
        p.parse_frame(bytes(raw))


def test_parse_frame_too_short():
    with pytest.raises(p.ProtocolError):
        p.parse_frame(b"\xfe\xb5")


def test_frame_error_text():
    assert p.Frame(cmd=1, code=22, token=bytes(8), payload=b"").error == "token timeout"
    assert p.Frame(cmd=1, code=99, token=bytes(8), payload=b"").error == "unknown error 99"


def test_identity_auth_request():
    frame = p.build_identity_auth("TACW1141521G5773", 12345, bytes(8))
    parsed = p.parse_frame(frame)
    assert parsed.cmd == p.CMD_IDENTITY_AUTH
    assert len(parsed.payload) == 130
    assert parsed.payload[:2] == b"\x80\x00"
    assert parsed.payload[2:58] != bytes(56)
    assert parsed.payload[58:] == bytes(72)


def test_identity_auth_is_deterministic():
    a = p.build_identity_auth("TACW-1", 1, bytes(8))
    b = p.build_identity_auth("TACW1", 1, bytes(8))
    assert a == b


def test_parse_identity_auth_success():
    payload = bytearray(34)
    payload[0] = 0x00
    payload[1:5] = b"HW#1"
    payload[21:24] = bytes([37, 8, 1])
    payload[24:26] = bytes([2, 3])
    payload[26:34] = TOKEN
    res = p.parse_identity_auth(bytes(payload))
    assert res.success
    assert res.token == TOKEN
    assert res.hardware_version == "HW1"
    assert res.software_version == "1.8.37"
    assert res.communication_version == "2.3"


def test_parse_identity_auth_failure():
    assert not p.parse_identity_auth(b"").success
    assert not p.parse_identity_auth(b"\xff" + bytes(40)).success
    assert not p.parse_identity_auth(bytes(10)).success


def test_sync_time_payload():
    frame = p.parse_frame(p.build_sync_time(TOKEN, utc_offset_hours=2))
    assert frame.cmd == p.CMD_SYNC_TIME
    assert len(frame.payload) == 5
    assert frame.payload[4] == 14
    assert struct.unpack("<I", frame.payload[:4])[0] > 1_700_000_000


def test_simple_request_payloads():
    assert p.parse_frame(p.build_read_status(TOKEN)).payload == b"\x00"
    assert p.parse_frame(p.build_start_charge(TOKEN)).payload == b"\x00\x00"
    assert p.parse_frame(p.build_stop_charge(TOKEN)).payload == b"\x00"
    assert p.parse_frame(p.build_query_power(TOKEN)).payload == b""
    assert p.parse_frame(p.build_power_control(TOKEN, 10)).payload == b"\x00\x0a"


def test_parse_read_status_idle():
    st = p.parse_read_status(b"\x00\x01")
    assert st.status == "idle"
    assert st.status_code == 0
    assert not st.charging
    assert st.power_w == 0


def test_parse_read_status_single_phase_charging():
    rest = bytes([0]) + struct.pack("<I", 42) + struct.pack("<H", 523)
    rest += struct.pack("<I", 23012) + struct.pack("<H", 1601)
    rest += struct.pack("<I", 3600) + bytes([16])
    st = p.parse_read_status(b"\x06" + rest)
    assert st.charging
    assert st.session_id == 42
    assert st.energy_kwh == 5.23
    assert st.voltage_l1 == 230.12
    assert st.current_l1 == 16.01
    assert st.duration_s == 3600
    assert st.rated_current == 16
    assert st.power_w == round(230.12 * 16.01, 1)


def test_parse_read_status_three_phase_charging():
    rest = bytes([1]) + struct.pack("<I", 7) + struct.pack("<H", 100)
    rest += struct.pack("<I", 23000) + struct.pack("<H", 1000)
    rest += struct.pack("<I", 23100) + struct.pack("<H", 1100)
    rest += struct.pack("<I", 23200) + struct.pack("<H", 1200)
    rest += struct.pack("<I", 120) + bytes([32])
    st = p.parse_read_status(b"\x06" + rest)
    assert st.phase_type == 1
    assert (st.voltage_l2, st.current_l2) == (231.0, 11.0)
    assert (st.voltage_l3, st.current_l3) == (232.0, 12.0)
    assert st.duration_s == 120
    assert st.rated_current == 32
    assert st.power_w == round(230 * 10 + 231 * 11 + 232 * 12, 1)


def test_parse_read_status_fault():
    st = p.parse_read_status(b"\x0f\x34\x12")
    assert st.status == "fault"
    assert st.fault_code == 0x1234


def test_parse_read_status_unknown_code():
    assert p.parse_read_status(b"\x09").status == "unknown_09"
    assert p.parse_read_status(b"").status == "unknown"


def test_parse_power_control():
    pc = p.parse_power_control(bytes.fromhex("001010"))
    assert (pc.port, pc.max_output_current, pc.output_current) == (0, 16, 16)
    assert p.parse_power_control(b"").max_output_current == 0


def test_parse_sys_info():
    payload = bytearray(60)
    payload[0:16] = b"TACW1141521G5773"
    payload[28:31] = bytes([5, 2, 1])
    payload[31:36] = b"TACW1"
    si = p.parse_sys_info(bytes(payload))
    assert si.device_number == "TACW1141521G5773"
    assert si.software_version == "1.2.5"
    assert si.software_model == "TACW1"


def test_parse_simple_result():
    assert p.parse_simple_result(b"") == 0
    assert p.parse_simple_result(b"\x01") == 1


def test_device_config_free_vending_bit():
    cfg = p.parse_device_config(b"\x05\x01")
    assert cfg.free_vending
    assert cfg.expand == 1
    assert cfg.with_free_vending(False) == 0x01
    assert p.parse_device_config(b"\x01").with_free_vending(True) == 0x05
    assert not p.parse_device_config(b"").free_vending


def test_set_device_config_payload():
    assert p.parse_frame(p.build_set_device_config(TOKEN, 0x05)).payload == b"\x05\x00"


def test_charge_mode_roundtrip_with_timezone():
    frame = p.parse_frame(p.build_set_charge_mode(TOKEN, True, time(1, 30), time(6, 15), utc_offset_hours=2))
    assert frame.cmd == p.CMD_SET_CHARGE_MODE
    assert frame.payload == bytes([1, 23, 30, 4, 15])
    sched = p.parse_charge_mode(frame.payload, utc_offset_hours=2)
    assert sched.enabled
    assert (sched.start, sched.end) == (time(1, 30), time(6, 15))


def test_charge_mode_disabled():
    assert p.parse_frame(p.build_set_charge_mode(TOKEN, False, time(1), time(2))).payload == bytes(5)
    sched = p.parse_charge_mode(b"\x00\x16\x00\x06\x00")
    assert not sched.enabled
    assert not p.parse_charge_mode(b"").enabled


def test_lock_frames_and_results():
    assert p.parse_frame(p.build_force_unlock(TOKEN)).cmd == p.CMD_FORCE_UNLOCK
    assert p.parse_frame(p.build_force_lock(TOKEN)).cmd == p.CMD_FORCE_LOCK
    assert p.parse_lock_result(b"\x00\x00\x00").ok
    res = p.parse_lock_result(b"\x00\x01\x00")
    assert not res.ok
    assert res.message == "no electronic lock"
    assert p.parse_lock_result(b"\x01\x02\x01").message == "lock not responding"


def test_charger_configuration_query_and_parse():
    frame = p.parse_frame(p.build_query_charger_configuration(TOKEN, p.CHARGER_CONFIG_ELOCK))
    assert frame.cmd == p.CMD_QUERY_CHARGER_CONFIGURATION
    assert frame.payload == b"\x03\x00"
    cc = p.parse_charger_configuration(b"\x03\x00\x00\x01\x00\x01")
    assert (cc.config_type, cc.result, cc.value) == (3, 0, 1)
    assert p.parse_charger_configuration(b"\x03\x00\x01").value is None
    assert p.parse_charger_configuration(b"").value is None
