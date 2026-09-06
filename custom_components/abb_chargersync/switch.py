"""Charging switch (start / stop)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .entity import AbbChargerEntity
from .protocol import ELOCK_LOCKED


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ents = []
    for c in entry.runtime_data.coordinators.values():
        ents.append(ChargingSwitch(c))
        if c.relay:
            ents += [FreeVendingSwitch(c), ScheduleSwitch(c), CableLockSwitch(c)]
    async_add_entities(ents)


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


class FreeVendingSwitch(AbbChargerEntity, SwitchEntity):
    """Charge without RFID authorisation."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "free_vending"
    _attr_icon = "mdi:card-off-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "free_vending")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.device_config is not None

    @property
    def is_on(self) -> bool | None:
        cfg = self.coordinator.data.device_config
        return cfg.free_vending if cfg else None

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.async_set_free_vending(enabled)
        except AbbApiError as err:
            raise HomeAssistantError(f"Free vending change failed: {err}") from err


class ScheduleSwitch(AbbChargerEntity, SwitchEntity):
    """Daily charging window stored on the charger."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator):
        super().__init__(coordinator, "schedule")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.schedule is not None

    @property
    def is_on(self) -> bool | None:
        sched = self.coordinator.data.schedule
        return sched.enabled if sched else None

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.async_set_schedule(enabled)
        except AbbApiError as err:
            raise HomeAssistantError(f"Schedule change failed: {err}") from err


class CableLockSwitch(AbbChargerEntity, SwitchEntity):
    """Force the cable lock closed or open (the app's cable-stuck screen)."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "cable_lock"
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator):
        super().__init__(coordinator, "cable_lock")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.lock_status is not None

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.lock_status
        return None if status is None else status == ELOCK_LOCKED

    async def async_turn_on(self, **kwargs) -> None:
        try:
            await self.coordinator.async_lock_cable()
        except AbbApiError as err:
            raise HomeAssistantError(f"Lock failed: {err}") from err

    async def async_turn_off(self, **kwargs) -> None:
        try:
            await self.coordinator.async_unlock_cable()
        except AbbApiError as err:
            raise HomeAssistantError(f"Unlock failed: {err}") from err
