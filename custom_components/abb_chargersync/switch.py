"""Charging switch (start / stop)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(ChargingSwitch(c) for c in entry.runtime_data.coordinators.values())


class ChargingSwitch(AbbChargerEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "charging"

    def __init__(self, coordinator):
        super().__init__(coordinator, "charging_switch")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        if d.status:
            return d.status.status_code in (0x02, 0x06, 0x07)
        return d.active_session is not None

    async def async_turn_on(self, **kwargs) -> None:
        try:
            await self.coordinator.async_start_charging()
        except AbbApiError as err:
            raise HomeAssistantError(f"Start charging failed: {err}") from err

    async def async_turn_off(self, **kwargs) -> None:
        try:
            await self.coordinator.async_stop_charging()
        except AbbApiError as err:
            raise HomeAssistantError(f"Stop charging failed: {err}") from err
