"""Data coordinator for one ABB charger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AbbApiError, AbbAuthError, AbbChargerOffline, AbbCloudClient, AbbRelayClient
from .const import DOMAIN
from .protocol import ChargeSchedule, ChargerStatus, DeviceConfig, PowerControl

_LOGGER = logging.getLogger(__name__)


@dataclass
class ChargerData:
    device: dict[str, Any]
    status: ChargerStatus | None = None
    power: PowerControl | None = None
    device_config: DeviceConfig | None = None
    schedule: ChargeSchedule | None = None
    lock_status: int | None = None
    relay_online: bool = False
    relay_error: str | None = None
    active_session: dict[str, Any] | None = None
    firmware: str = ""
    hardware: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class AbbChargerCoordinator(DataUpdateCoordinator[ChargerData]):
    """Polls cloud metadata + charger status through the relay."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: AbbCloudClient,
        relay: AbbRelayClient | None,
        device: dict[str, Any],
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device['deviceNumber']}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.cloud = cloud
        self.relay = relay
        self.device_id = int(device["id"])
        self.device_number = device["deviceNumber"]
        self._device = device
        self._power_counter = 0
        self._settings_dirty = True
        self._schedule_times: tuple[dtime, dtime] = (dtime(22, 0), dtime(6, 0))

    async def _async_update_data(self) -> ChargerData:
        data = ChargerData(device=self._device)
        try:
            data.device = self._device = await self.cloud.get_device(self.device_id)
        except AbbAuthError as err:
            raise UpdateFailed(f"cloud auth: {err}") from err
        except AbbApiError as err:
            _LOGGER.debug("cloud device fetch failed: %s", err)
        try:
            sessions = await self.cloud.get_active_sessions(self.device_id)
            data.active_session = sessions[0] if sessions else None
        except AbbApiError as err:
            _LOGGER.debug("active sessions fetch failed: %s", err)

        if self.relay is not None and data.device.get("online", 1):
            try:
                data.status = await self.relay.read_status()
                data.relay_online = True
                data.firmware = self.relay.firmware_version
                data.hardware = self.relay.hardware_version
                self._power_counter += 1
                prev = self.data if self.data else None
                if prev is None or prev.power is None or self._settings_dirty or self._power_counter >= 5:
                    self._power_counter = 0
                    self._settings_dirty = False
                    data.power = await self.relay.read_power_control()
                    await self._read_settings(data)
                else:
                    data.power = prev.power
                    data.device_config = prev.device_config
                    data.schedule = prev.schedule
                    data.lock_status = prev.lock_status
            except AbbChargerOffline as err:
                data.relay_error = str(err)
                await self.relay.close()
            except AbbAuthError as err:
                data.relay_error = f"auth: {err}"
                await self.relay.close()
            except AbbApiError as err:
                data.relay_error = str(err)
                await self.relay.close()
            except Exception as err:  # noqa: BLE001
                data.relay_error = f"unexpected: {err}"
                _LOGGER.exception("relay update failed")
                await self.relay.close()
            if data.relay_error:
                _LOGGER.debug("relay unavailable for %s: %s", self.device_number, data.relay_error)
                if self.data:
                    data.firmware = self.data.firmware
                    data.hardware = self.data.hardware
                    data.power = self.data.power
                    data.device_config = self.data.device_config
                    data.schedule = self.data.schedule
                    data.lock_status = self.data.lock_status
        return data

    @property
    def utc_offset_hours(self) -> int:
        offset = dt_util.now().utcoffset()
        return int(offset.total_seconds() // 3600) if offset else 0

    async def _read_settings(self, data: ChargerData) -> None:
        """Rarely changing settings; each is optional so one unsupported command does not break the poll."""
        assert self.relay is not None
        for name, reader in (
            ("device_config", self.relay.read_device_config),
            ("schedule", lambda: self.relay.read_schedule(self.utc_offset_hours)),
            ("lock_status", self.relay.read_lock_status),
        ):
            try:
                setattr(data, name, await reader())
            except AbbChargerOffline:
                raise
            except AbbApiError as err:
                _LOGGER.debug("%s read failed for %s: %s", name, self.device_number, err)
        if data.schedule and data.schedule.enabled:
            self._schedule_times = (data.schedule.start, data.schedule.end)

    def _require_relay(self) -> AbbRelayClient:
        if not self.relay:
            raise AbbApiError("this setting requires the relay connection")
        return self.relay

    async def async_set_free_vending(self, enabled: bool) -> None:
        await self._require_relay().set_free_vending(enabled)
        self._settings_dirty = True
        await self.async_request_refresh()

    @property
    def schedule_times(self) -> tuple[dtime, dtime]:
        """Window to apply when the schedule is enabled; kept while it is disabled."""
        return self._schedule_times

    async def async_set_schedule(self, enabled: bool, start: dtime | None = None, end: dtime | None = None) -> None:
        cur_start, cur_end = self._schedule_times
        self._schedule_times = (start or cur_start, end or cur_end)
        if not enabled and self.data and self.data.schedule and not self.data.schedule.enabled:
            self.async_update_listeners()
            return
        await self._require_relay().set_schedule(enabled, *self._schedule_times, self.utc_offset_hours)
        self._settings_dirty = True
        await self.async_request_refresh()

    async def async_unlock_cable(self) -> None:
        await self._require_relay().unlock_cable()
        self._settings_dirty = True
        await self.async_request_refresh()

    async def async_lock_cable(self) -> None:
        await self._require_relay().lock_cable()
        self._settings_dirty = True
        await self.async_request_refresh()

    async def async_shutdown_relay(self) -> None:
        if self.relay:
            await self.relay.close()

    async def async_start_charging(self) -> None:
        if self.relay:
            await self.relay.start_charging()
        else:
            await self.cloud.cloud_start_session(self.device_id)
        await self.async_request_refresh()

    async def async_stop_charging(self) -> None:
        if self.relay:
            await self.relay.stop_charging()
        elif self.data and self.data.active_session:
            await self.cloud.cloud_stop_session(str(self.data.active_session["id"]))
        await self.async_request_refresh()

    async def async_request_report(
        self,
        start: datetime | date,
        end: datetime | date,
        fmt: str = "pdf",
        email: str | None = None,
        company_only: bool | None = None,
    ) -> str:
        return await self.cloud.export_sessions(
            self.device_id, start, end, fmt=fmt, email=email, company_only=company_only
        )

    async def async_set_max_current(self, amps: int) -> None:
        await self._require_relay().set_max_current(amps)
        self._settings_dirty = True
        await self.async_request_refresh()
