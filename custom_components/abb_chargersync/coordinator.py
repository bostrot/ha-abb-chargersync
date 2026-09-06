"""Data coordinator for one ABB charger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AbbApiError, AbbAuthError, AbbChargerOffline, AbbCloudClient, AbbRelayClient
from .const import DOMAIN
from .protocol import ChargerStatus, PowerControl

_LOGGER = logging.getLogger(__name__)


@dataclass
class ChargerData:
    device: dict[str, Any]
    status: ChargerStatus | None = None
    power: PowerControl | None = None
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
                prev = self.data.power if self.data else None
                if prev is None or self._power_counter >= 5:
                    self._power_counter = 0
                    data.power = await self.relay.read_power_control()
                else:
                    data.power = prev
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
        return data

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
        if not self.relay:
            raise AbbApiError("max current requires the relay connection")
        await self.relay.set_max_current(amps)
        self._power_counter = 99
        await self.async_request_refresh()
