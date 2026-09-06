import asyncio
import json
from datetime import date, datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.abb_chargersync import api
from custom_components.abb_chargersync import protocol as proto

TOKEN = bytes.fromhex("F94734D26AC0F1D1")


def _relay_frame(cmd: int, payload: bytes, code: int = 0) -> str:
    frame = bytearray(proto.build_frame(cmd, payload, TOKEN))
    frame[0] = 0xAA
    frame[2] = code
    chk = 0
    for i, b in enumerate(frame):
        if i != 7:
            chk ^= b
    frame[7] = chk
    return frame.hex().upper()


class FakeCloud:
    """Minimal abb-user.chargedot.com stand-in."""

    def __init__(self) -> None:
        self.token_requests: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.reject_login = False
        self.expire_first_token = False
        self.app = web.Application()
        self.app.router.add_post("/api/oauth/token", self.token)
        self.app.router.add_get("/api/v2/users/me", self.me)
        self.app.router.add_get("/api/v2/devices", self.devices)
        self.app.router.add_post("/api/v2/devices/{id}/sessions/active", self.active)
        self.app.router.add_post("/api/v2/devices/{id}/sessions/export", self.export)
        self.app.router.add_get("/api/v2/devices/{id}/price", self.get_price)
        self.app.router.add_post("/api/v2/devices/{id}/price", self.set_price)
        self.app.router.add_get("/api/v2/currencies", self.currencies)
        self.app.router.add_get("/api/v2/devices/upgrade-rules/upgrade", self.upgrade_rule)
        self.exports: list[dict] = []
        self.plans: list[dict] = []
        self.plan: dict | None = {"open": 2, "currencyType": 3, "averagePrice": "0.30", "onPeakPrice": "0.40"}
        self.rule_queries: list[dict] = []

    async def token(self, request: web.Request) -> web.Response:
        form = dict(await request.post())
        self.token_requests.append(form)
        if self.reject_login:
            return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response(
            {"access_token": f"tok{len(self.token_requests)}", "refresh_token": "ref", "expires_in": 3600}
        )

    async def me(self, request: web.Request) -> web.Response:
        self.calls.append(("GET", "me"))
        if request.headers.get("Authorization") == "Bearer tok1" and self.expire_first_token:
            return web.Response(status=401)
        assert request.headers["X-APP-VERSION"] == api.APP_VERSION
        return web.json_response({"id": 4711, "sessionId": "sess-abc", "authen": "account@example.com"})

    async def devices(self, request: web.Request) -> web.Response:
        return web.json_response([{"id": 1, "deviceNumber": "TACW1"}])

    async def active(self, request: web.Request) -> web.Response:
        return web.json_response({"status": 404, "msg": "Not found"}, status=404)

    async def get_price(self, request: web.Request) -> web.Response:
        if self.plan is None:
            return web.json_response({"msg": "Not found"}, status=404)
        return web.json_response(self.plan)

    async def set_price(self, request: web.Request) -> web.Response:
        self.plans.append(await request.json())
        return web.Response(text="ok")

    async def currencies(self, request: web.Request) -> web.Response:
        return web.json_response([{"currencyType": 3, "name": "EUR", "symbol": "€"}])

    async def upgrade_rule(self, request: web.Request) -> web.Response:
        self.rule_queries.append(dict(request.query))
        return web.json_response({"rule": {"version": "1.8.40", "ruleIsForUpdate": True, "packageInfo": {"name": "TACW 1.8.40"}}})

    async def export(self, request: web.Request) -> web.Response:
        self.exports.append({"id": request.match_info["id"], **(await request.json())})
        return web.json_response({})


@pytest.fixture
async def cloud_env():
    fake = FakeCloud()
    client = TestClient(TestServer(fake.app))
    await client.start_server()
    real_host = api.API_HOST
    api.API_HOST = str(client.make_url("/"))
    try:
        yield fake, client.session
    finally:
        api.API_HOST = real_host
        await client.close()


async def test_login_and_user(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    await cloud.login()
    assert fake.token_requests[0]["grant_type"] == "password"
    assert fake.token_requests[0]["client_id"] == api.CLIENT_ID
    assert cloud.access_token == "tok1"
    user = await cloud.get_user()
    assert user["id"] == 4711
    assert cloud.user_id == 4711
    assert cloud.session_id == "sess-abc"


async def test_login_rejected(cloud_env):
    fake, session = cloud_env
    fake.reject_login = True
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    with pytest.raises(api.AbbAuthError):
        await cloud.login()


async def test_request_retries_once_on_401(cloud_env):
    fake, session = cloud_env
    fake.expire_first_token = True
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    await cloud.get_user()
    assert len(fake.token_requests) == 2
    assert cloud.access_token == "tok2"


async def test_refresh_uses_refresh_token(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    await cloud.login()
    cloud._expires_at = 0
    await cloud.ensure_token()
    assert fake.token_requests[1]["grant_type"] == "refresh_token"
    assert fake.token_requests[1]["refresh_token"] == "ref"


async def test_active_sessions_404_means_none(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    assert await cloud.get_active_sessions(1) == []


async def test_export_sessions_defaults_to_account_email(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    recipient = await cloud.export_sessions(1, date(2026, 9, 1), date(2026, 9, 6))
    assert recipient == "account@example.com"
    assert fake.exports == [
        {
            "id": "1",
            "startTime": "2026-09-01 00:00:00",
            "endTime": "2026-09-06 23:59:59",
            "cardNumber": None,
            "format": "pdf",
            "email": "account@example.com",
            "isCompanyCarSession": None,
        }
    ]


async def test_export_sessions_with_overrides(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    await cloud.export_sessions(
        7,
        datetime(2026, 8, 1, 6, 30),
        datetime(2026, 8, 31, 18, 0),
        fmt="csv",
        email="other@example.com",
        card_number="CARD1",
        company_only=True,
    )
    body = fake.exports[0]
    assert body["startTime"] == "2026-08-01 06:30:00"
    assert body["endTime"] == "2026-08-31 18:00:00"
    assert body["format"] == "csv"
    assert body["email"] == "other@example.com"
    assert body["cardNumber"] == "CARD1"
    assert body["isCompanyCarSession"] is True


async def test_export_sessions_rejects_unknown_format(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    with pytest.raises(api.AbbApiError):
        await cloud.export_sessions(1, date(2026, 9, 1), date(2026, 9, 6), fmt="docx")
    assert fake.exports == []


async def test_energy_plan_roundtrip(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    plan = await cloud.get_energy_plan(1)
    assert plan["open"] == 2
    plan["averagePrice"] = "0.35"
    await cloud.set_energy_plan(1, plan)
    body = fake.plans[0]
    assert body["averagePrice"] == "0.35"
    assert body["onPeakPrice"] == "0.40"
    assert body["midPeakSt"] == ""
    assert body["open"] == 2
    assert body["currencyType"] == 3
    assert set(body) == set(api.ENERGY_PLAN_FIELDS) | {"open", "currencyType"}


async def test_energy_plan_missing_is_none(cloud_env):
    fake, session = cloud_env
    fake.plan = None
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    assert await cloud.get_energy_plan(1) is None


async def test_currencies_and_upgrade_rule(cloud_env):
    fake, session = cloud_env
    cloud = api.AbbCloudClient(session, "me@example.com", "pw")
    assert (await cloud.get_currencies())[0]["symbol"] == "€"
    rule = await cloud.get_upgrade_rule("1.8.37", "TACW1", "HW1")
    assert rule["version"] == "1.8.40"
    assert fake.rule_queries[0] == {"currentVersion": "1.8.37", "deviceNumber": "TACW1", "hardwareVersion": "HW1"}


class FakeRelay:
    """Minimal remote-control relay stand-in."""

    def __init__(self) -> None:
        self.logins: list[dict[str, str]] = []
        self.received: list[bytes] = []
        self.accept = {"sess-abc"}
        self.app = web.Application()
        self.app.router.add_get("/ws/login", self.handler)

    async def handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.logins.append(dict(request.query))
        if request.query.get("t") not in self.accept:
            await ws.send_json({"method": "login", "code": 1, "msg": "Authentication failed"})
            await ws.close()
            return ws
        await ws.send_json({"method": "login", "code": 0})
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            data = json.loads(msg.data)
            if data.get("method") == "ping":
                await ws.send_json({"method": "pong"})
                continue
            frame = proto.parse_frame(bytes.fromhex(data["data"]))
            self.received.append(frame.payload)
            await ws.send_json(
                {
                    "method": "remote_control",
                    "code": 0,
                    "data": {"deviceNumber": data["to"], "raw": self.reply(frame)},
                }
            )
        return ws

    def reply(self, frame: proto.Frame) -> str:
        if frame.cmd == proto.CMD_IDENTITY_AUTH:
            payload = bytearray(34)
            payload[1:4] = b"HW1"
            payload[21:24] = bytes([37, 8, 1])
            payload[26:34] = TOKEN
            return _relay_frame(frame.cmd, bytes(payload))
        if frame.cmd == proto.CMD_SYNC_TIME:
            return _relay_frame(frame.cmd, b"")
        if frame.cmd == proto.CMD_READ_STATUS:
            return _relay_frame(frame.cmd, b"\x00\x01")
        if frame.cmd == proto.CMD_QUERY_POWER_PERCENT:
            return _relay_frame(frame.cmd, bytes.fromhex("001010"))
        if frame.cmd == proto.CMD_POWER_CONTROL:
            return _relay_frame(frame.cmd, b"\x00")
        return _relay_frame(frame.cmd, b"", code=21)


@pytest.fixture
async def relay_env(cloud_env):
    fake_cloud, session = cloud_env
    fake = FakeRelay()
    client = TestClient(TestServer(fake.app))
    await client.start_server()
    real_host = api.WS_HOST
    api.WS_HOST = str(client.make_url("")).rstrip("/")
    cloud = api.AbbCloudClient(session, "me+ha@example.com", "pw")
    relay = api.AbbRelayClient(session, cloud, "TACW1", 1)
    try:
        yield fake, relay
    finally:
        await relay.close()
        api.WS_HOST = real_host
        await client.close()


async def test_relay_logs_in_with_session_id_and_authenticates(relay_env):
    fake, relay = relay_env
    await relay.ensure_session()
    assert fake.logins[0]["t"] == "sess-abc"
    assert fake.logins[0]["e"] == "me+ha@example.com"
    assert relay.authenticated
    assert relay.firmware_version == "1.8.37"
    assert relay.hardware_version == "HW1"
    assert relay._token == TOKEN


async def test_relay_falls_back_to_access_token(relay_env):
    fake, relay = relay_env
    fake.accept = {"tok1"}
    await relay.ensure_session()
    assert [login["t"] for login in fake.logins] == ["sess-abc", "tok1"]
    assert relay.connected


async def test_relay_login_rejected_everywhere(relay_env):
    fake, relay = relay_env
    fake.accept = set()
    with pytest.raises(api.AbbAuthError):
        await relay.ensure_session()
    assert not relay.connected


async def test_relay_commands(relay_env):
    fake, relay = relay_env
    status = await relay.read_status()
    assert status.status == "idle"
    power = await relay.read_power_control()
    assert power.max_output_current == 16
    await relay.set_max_current(10)
    assert fake.received[-1] == b"\x00\x0a"
    with pytest.raises(api.AbbApiError):
        await relay.sys_info()


async def test_relay_offline_push_fails_pending(relay_env):
    fake, relay = relay_env
    await relay.ensure_session()
    fut = asyncio.get_running_loop().create_future()
    relay._pending[proto.CMD_READ_STATUS] = fut
    relay._handle_message(json.dumps({"method": "update_device_status", "data": {"status": 3}}))
    with pytest.raises(api.AbbChargerOffline):
        fut.result()
    assert relay.device_status == 3
