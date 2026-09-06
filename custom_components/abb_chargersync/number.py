"""Max charging current."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ents = []
    for c in entry.runtime_data.coordinators.values():
        if c.relay:
            ents.append(MaxCurrentNumber(c))
        ents += [EnergyPriceNumber(c, key) for key in PRICE_KEYS]
    async_add_entities(ents)


PRICE_KEYS = {
    "average_price": "averagePrice",
    "on_peak_price": "onPeakPrice",
    "mid_peak_price": "midPeakPrice",
    "off_peak_price": "offPeakPrice",
}


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


class EnergyPriceNumber(AbbChargerEntity, NumberEntity):
    """One tariff of the cloud energy plan, in currency units per kWh."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 0.001
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._field = PRICE_KEYS[key]
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.energy_plan is not None

    @property
    def native_unit_of_measurement(self) -> str | None:
        plan = self.coordinator.data.energy_plan or {}
        for c in self.coordinator.data.currencies:
            if c.get("currencyType") == plan.get("currencyType") and c.get("symbol"):
                return f"{c['symbol']}/kWh"
        return None

    @property
    def native_value(self) -> float | None:
        plan = self.coordinator.data.energy_plan or {}
        raw = plan.get(self._field)
        try:
            return float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.async_update_energy_plan(**{self._field: f"{value:.3f}".rstrip("0").rstrip(".")})
        except AbbApiError as err:
            raise HomeAssistantError(f"Energy plan update failed: {err}") from err
