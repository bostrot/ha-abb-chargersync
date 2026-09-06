"""Cloud REST client and remote-control relay client for ABB ChargerSync."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any
from urllib.parse import quote

import aiohttp

from . import protocol as proto

_LOGGER = logging.getLogger(__name__)

API_HOST = "https://abb-user.chargedot.com/"
WS_HOST = "wss://abb.api.chargedot.com:18971"
CLIENT_ID = "3710400e-1c02-4175-84ea-40a227c0dcf6"
CLIENT_SECRET = "f1a6d022-8a8e-453c-862e-ba0d3c5b4521"
APP_VERSION = "3.5.0"

REPORT_FORMATS = ("pdf", "csv", "excel")

WS_PING_INTERVAL = 30
WS_RESPONSE_TIMEOUT = 15


class AbbApiError(Exception):
    """Generic API error."""


class AbbAuthError(AbbApiError):
    """Bad credentials or expired token."""


class AbbChargerOffline(AbbApiError):
    """Charger not reachable through the relay."""


class AbbCloudClient:
    """REST client for abb-user.chargedot.com."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self.email = email
        self._password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._expires_at: float = 0
        self.user_id: int | None = None
        self.session_id: str | None = None
        self.account_email: str | None = None
        self._lock = asyncio.Lock()

    async def login(self) -> None:
        await self._token_request(
            {
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "username": self.email,
                "password": self._password,
            }
        )

    async def _refresh(self) -> None:
        if not self.refresh_token:
            await self.login()
            return
        try:
            await self._token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "refresh_token": self.refresh_token,
                }
            )
        except AbbAuthError:
            await self.login()

    async def _token_request(self, data: dict[str, str]) -> None:
        async with self._session.post(
            API_HOST + "api/oauth/token",
            data=data,
            headers={"X-APP-VERSION": APP_VERSION, "Accept": "application/json"},
        ) as resp:
            if resp.status in (400, 401, 403):
                raise AbbAuthError(f"login failed ({resp.status}): {await resp.text()}")
            if resp.status >= 400:
                raise AbbApiError(f"token request failed ({resp.status}): {await resp.text()}")
            body = await resp.json(content_type=None)
        self.access_token = body.get("access_token")
        self.refresh_token = body.get("refresh_token") or self.refresh_token
        self._expires_at = time.time() + float(body.get("expires_in", 3600)) - 60
        if not self.access_token:
            raise AbbAuthError(f"no access_token in response: {body}")

    async def ensure_token(self) -> str:
        async with self._lock:
            if not self.access_token:
                await self.login()
            elif time.time() >= self._expires_at:
                await self._refresh()
            return self.access_token  # type: ignore[return-value]

    async def request(self, method: str, path: str, retry: bool = True, **kwargs: Any) -> Any:
        token = await self.ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-APP-VERSION": APP_VERSION,
            "Accept": "application/json",
        }
        async with self._session.request(method, API_HOST + path.lstrip("/"), headers=headers, **kwargs) as resp:
            if resp.status == 401 and retry:
                self.access_token = None
                return await self.request(method, path, retry=False, **kwargs)
            if resp.status >= 400:
                raise AbbApiError(f"{method} {path} -> {resp.status}: {await resp.text()}")
            if resp.content_type and "json" in resp.content_type:
                return await resp.json()
            return await resp.text()

    async def get_user(self) -> dict[str, Any]:
        user = await self.request("GET", "api/v2/users/me")
        self.user_id = int(user["id"])
        self.session_id = user.get("sessionId") or None
        self.account_email = user.get("authen") or None
        return user

    async def get_devices(self) -> list[dict[str, Any]]:
        return await self.request("GET", "api/v2/devices")

    async def get_device(self, device_id: int) -> dict[str, Any]:
        return await self.request("GET", f"api/v2/devices/{device_id}")

    async def get_active_sessions(self, device_id: int) -> list[dict[str, Any]]:
        try:
            res = await self.request("POST", f"api/v2/devices/{device_id}/sessions/active")
        except AbbApiError as err:
            if "-> 404" in str(err):
                return []
            raise
        if isinstance(res, dict):
            return [res] if res else []
        return res or []

    async def cloud_start_session(self, device_id: int) -> Any:
        return await self.request("POST", f"api/v2/devices/{device_id}/sessions/active")

    async def cloud_stop_session(self, session_id: str) -> Any:
        return await self.request("DELETE", f"api/v2/active-sessions/{session_id}")

    async def export_sessions(
        self,
        device_id: int,
        start: datetime | date,
        end: datetime | date,
        fmt: str = "pdf",
        email: str | None = None,
        card_number: str | None = None,
        company_only: bool | None = None,
    ) -> str:
        """Ask the cloud to e-mail a session report. Returns the recipient address."""
        if fmt not in REPORT_FORMATS:
            raise AbbApiError(f"unsupported report format {fmt!r}")
        recipient = email or self.account_email
        if not recipient:
            await self.get_user()
            recipient = self.account_email or self.email
        body = {
            "startTime": _api_datetime(start, end_of_day=False),
            "endTime": _api_datetime(end, end_of_day=True),
            "cardNumber": card_number,
            "format": fmt,
            "email": recipient,
            "isCompanyCarSession": company_only,
        }
        await self.request("POST", f"api/v2/devices/{device_id}/sessions/export", json=body)
        return recipient

    async def get_auto_export(self, device_id: int) -> dict[str, Any]:
        return await self.request("GET", f"api/v2/devices/{device_id}/sessions/auto-export")

    async def get_schedules(self, device_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"api/v2/devices/{device_id}/schedules")

    async def get_sessions(self, device_id: int, page: int = 1, per_page: int = 10) -> dict[str, Any]:
        return await self.request(
            "GET", f"api/v2/devices/{device_id}/sessions", params={"page": page, "per_page": per_page}
        )


def _api_datetime(value: datetime | date, end_of_day: bool) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return f"{value:%Y-%m-%d} {'23:59:59' if end_of_day else '00:00:00'}"


class AbbRelayClient:
    """WebSocket relay connection and charger session for a single charger."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        cloud: AbbCloudClient,
        device_number: str,
        device_id: int,
    ) -> None:
        self._session = session
        self._cloud = cloud
        self.device_number = device_number
        self.device_id = device_id
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task | None = None
        self._pinger: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._token = bytes(8)
        self.authenticated = False
        self.firmware_version = ""
        self.hardware_version = ""
        self._lock = asyncio.Lock()
        self.device_status: int | None = None
        self._relay_variant: str | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        if self.connected:
            return
        access = await self._cloud.ensure_token()
        if self._cloud.user_id is None or self._cloud.session_id is None:
            try:
                await self._cloud.get_user()
            except AbbApiError as err:
                _LOGGER.debug("users/me failed before relay connect: %s", err)
        email = quote(self._cloud.email, safe="")
        # The relay expects the profile's sessionId; the OAuth token is kept as a fallback.
        candidates: list[tuple[str, str]] = []
        if self._cloud.session_id:
            candidates.append(("sessionId", f"{WS_HOST}/ws/login?t={self._cloud.session_id}&v=1&e={email}"))
        candidates.append(("access_token", f"{WS_HOST}/ws/login?t={access}&v=1&e={email}"))
        if self._relay_variant:
            candidates.sort(key=lambda c: c[0] != self._relay_variant)
        last_err: Exception | None = None
        for name, url in candidates:
            try:
                await self._connect_url(url)
            except AbbAuthError as err:
                last_err = err
                _LOGGER.debug("relay login with %s rejected: %s", name, err)
                continue
            if self._relay_variant != name:
                _LOGGER.info("Relay login for %s accepted using %s", self.device_number, name)
            self._relay_variant = name
            return
        raise last_err or AbbApiError("relay login failed")

    async def _connect_url(self, url: str) -> None:
        self._ws = await asyncio.wait_for(self._session.ws_connect(url, heartbeat=None), 20)
        self.authenticated = False
        self._token = bytes(8)
        login_fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[-1] = login_fut
        self._reader = asyncio.create_task(self._read_loop())
        try:
            await asyncio.wait_for(login_fut, WS_RESPONSE_TIMEOUT)
        except asyncio.TimeoutError as err:
            await self.close()
            raise AbbApiError("relay login timeout") from err
        except AbbAuthError:
            await self.close()
            raise
        self._pinger = asyncio.create_task(self._ping_loop())

    async def close(self) -> None:
        self.authenticated = False
        for t in (self._pinger, self._reader):
            if t and not t.done():
                t.cancel()
        self._pinger = self._reader = None
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ws = None
        self._fail_pending(AbbApiError("connection closed"))

    def _fail_pending(self, err: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()

    async def _ping_loop(self) -> None:
        try:
            while self.connected:
                await asyncio.sleep(WS_PING_INTERVAL)
                if self.connected:
                    await self._ws.send_str(json.dumps({"method": "ping"}))  # type: ignore[union-attr]
        except asyncio.CancelledError:
            pass
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ping loop ended: %s", err)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            return
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("relay read loop error: %s", err)
        self.authenticated = False
        self._fail_pending(AbbApiError("relay connection closed"))

    def _handle_message(self, text: str) -> None:
        _LOGGER.debug("relay <- %s", text)
        try:
            msg = json.loads(text)
        except ValueError:
            return
        method = msg.get("method")
        if method == "login":
            fut = self._pending.pop(-1, None)
            if fut and not fut.done():
                if msg.get("code", -1) == 0:
                    fut.set_result(True)
                else:
                    fut.set_exception(AbbAuthError(f"relay login rejected: {msg}"))
            return
        if method == "update_device_status":
            self.device_status = (msg.get("data") or {}).get("status")
            if self.device_status in (1, 3, -1):
                _LOGGER.info("Charger %s reported offline by relay (status=%s)", self.device_number, self.device_status)
                self._fail_pending(AbbChargerOffline("charger offline"))
            return
        if method == "remote_control":
            code = msg.get("code", -1)
            if code == 401:
                self._fail_pending(AbbAuthError("relay returned 401"))
                return
            if code != 0:
                _LOGGER.debug("remote_control code %s: %s", code, msg)
                return
            data = msg.get("data") or {}
            if data.get("deviceNumber") not in (None, self.device_number):
                return
            raw = data.get("raw")
            if not raw:
                return
            try:
                frame = proto.parse_frame(bytes.fromhex(raw))
            except (ValueError, proto.ProtocolError) as err:
                _LOGGER.debug("bad frame %s: %s", raw, err)
                return
            fut = self._pending.pop(frame.cmd, None)
            if fut and not fut.done():
                fut.set_result(frame)
            else:
                _LOGGER.debug("unsolicited frame cmd=0x%02x code=%s", frame.cmd, frame.code)

    async def _send(self, cmd: int, frame: bytes, timeout: float = WS_RESPONSE_TIMEOUT) -> proto.Frame:
        if not self.connected:
            raise AbbApiError("relay not connected")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        old = self._pending.pop(cmd, None)
        if old and not old.done():
            old.cancel()
        self._pending[cmd] = fut
        payload = json.dumps({"method": "remote_control", "to": self.device_number, "data": frame.hex().upper()})
        _LOGGER.debug("relay -> %s", payload)
        await self._ws.send_str(payload)  # type: ignore[union-attr]
        try:
            resp: proto.Frame = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as err:
            self._pending.pop(cmd, None)
            raise AbbChargerOffline(f"no response from charger for cmd 0x{cmd:02x}") from err
        if resp.code == proto.CODE_TOKEN_TIMEOUT:
            self.authenticated = False
            raise AbbAuthError("charger token timed out")
        if resp.code != 0:
            raise AbbApiError(f"charger error for cmd 0x{cmd:02x}: {resp.error}")
        return resp

    async def authenticate(self) -> None:
        if self._cloud.user_id is None:
            await self._cloud.get_user()
        frame = proto.build_identity_auth(self.device_number, self._cloud.user_id or 0, bytes(8))
        resp = await self._send(proto.CMD_IDENTITY_AUTH, frame)
        res = proto.parse_identity_auth(resp.payload)
        if not res.success or not res.token:
            raise AbbAuthError("charger identity auth failed")
        self._token = res.token
        self.firmware_version = res.software_version
        self.hardware_version = res.hardware_version
        self.authenticated = True
        _LOGGER.debug("Authenticated with %s (fw %s hw %s)", self.device_number, res.software_version, res.hardware_version)
        try:
            await self._send(proto.CMD_SYNC_TIME, proto.build_sync_time(self._token))
        except AbbApiError as err:
            _LOGGER.debug("sync time failed: %s", err)

    async def ensure_session(self) -> None:
        async with self._lock:
            if not self.connected:
                await self.connect()
            if not self.authenticated:
                await self.authenticate()

    async def _command(self, cmd: int, build, *args: Any) -> proto.Frame:
        await self.ensure_session()
        try:
            return await self._send(cmd, build(self._token, *args))
        except AbbAuthError:
            await self.close()
            await self.ensure_session()
            return await self._send(cmd, build(self._token, *args))

    async def read_status(self) -> proto.ChargerStatus:
        resp = await self._command(proto.CMD_READ_STATUS, proto.build_read_status)
        return proto.parse_read_status(resp.payload)

    async def read_power_control(self) -> proto.PowerControl:
        resp = await self._command(proto.CMD_QUERY_POWER_PERCENT, proto.build_query_power)
        return proto.parse_power_control(resp.payload)

    async def set_max_current(self, amps: int) -> None:
        resp = await self._command(proto.CMD_POWER_CONTROL, proto.build_power_control, amps)
        if proto.parse_simple_result(resp.payload) != 0:
            raise AbbApiError("charger rejected max current")

    async def start_charging(self) -> None:
        resp = await self._command(proto.CMD_START_CHARGE, proto.build_start_charge)
        if proto.parse_simple_result(resp.payload) != 0:
            raise AbbApiError("charger rejected start command")

    async def stop_charging(self) -> None:
        await self._command(proto.CMD_STOP_CHARGE, proto.build_stop_charge)

    async def read_device_config(self) -> proto.DeviceConfig:
        resp = await self._command(proto.CMD_QUERY_DEVICE_CONFIG, proto.build_query_device_config)
        return proto.parse_device_config(resp.payload)

    async def set_free_vending(self, enabled: bool) -> proto.DeviceConfig:
        current = await self.read_device_config()
        resp = await self._command(proto.CMD_SET_DEVICE_CONFIG, proto.build_set_device_config, current.with_free_vending(enabled))
        if proto.parse_simple_result(resp.payload) != 0:
            raise AbbApiError("charger rejected device configuration")
        updated = await self.read_device_config()
        if updated.free_vending != enabled:
            raise AbbApiError("charger did not apply free vending setting")
        return updated

    async def read_schedule(self, utc_offset_hours: int = 0) -> proto.ChargeSchedule:
        resp = await self._command(proto.CMD_QUERY_CHARGE_MODE, proto.build_query_charge_mode)
        return proto.parse_charge_mode(resp.payload, utc_offset_hours)

    async def set_schedule(self, enabled: bool, start: dtime, end: dtime, utc_offset_hours: int = 0) -> proto.ChargeSchedule:
        resp = await self._command(proto.CMD_SET_CHARGE_MODE, proto.build_set_charge_mode, enabled, start, end, utc_offset_hours)
        if proto.parse_simple_result(resp.payload) != 0:
            raise AbbApiError("charger rejected schedule")
        return await self.read_schedule(utc_offset_hours)

    async def unlock_cable(self) -> None:
        resp = await self._command(proto.CMD_FORCE_UNLOCK, proto.build_force_unlock)
        res = proto.parse_lock_result(resp.payload)
        if not res.ok:
            raise AbbApiError(f"unlock failed: {res.message}")

    async def lock_cable(self) -> None:
        resp = await self._command(proto.CMD_FORCE_LOCK, proto.build_force_lock)
        res = proto.parse_lock_result(resp.payload)
        if not res.ok:
            raise AbbApiError(f"lock failed: {res.message}")

    async def read_lock_status(self) -> int | None:
        resp = await self._command(
            proto.CMD_QUERY_CHARGER_CONFIGURATION, proto.build_query_charger_configuration, proto.CHARGER_CONFIG_ELOCK
        )
        return proto.parse_charger_configuration(resp.payload).value

    async def sys_info(self) -> proto.SysInfo:
        resp = await self._command(proto.CMD_READ_SYS_INFO, proto.build_query_sys_info)
        return proto.parse_sys_info(resp.payload)
