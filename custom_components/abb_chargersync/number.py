"""Max charging current."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(MaxCurrentNumber(c) for c in entry.runtime_data.coordinators.values() if c.relay)


class MaxCurrentNumber(AbbChargerEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_step = 1
    _attr_native_min_value = 6
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "max_current"

    def __init__(self, coordinator):
        super().__init__(coordinator, "max_current")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.power is not None

    @property
    def native_max_value(self) -> float:
        p = self.coordinator.data.power
        rated = self.coordinator.data.device.get("ratedCurrent") or 32
        return float(p.max_output_current or rated) if p else float(rated)

    @property
    def native_value(self) -> float | None:
        p = self.coordinator.data.power
        return float(p.output_current) if p else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.async_set_max_current(int(value))
        except AbbApiError as err:
            raise HomeAssistantError(f"Could not set max current: {err}") from err
