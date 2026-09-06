"""Energy plan mode and currency."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .const import ENERGY_PLAN_MODES
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ents = []
    for c in entry.runtime_data.coordinators.values():
        ents += [EnergyPlanModeSelect(c), CurrencySelect(c)]
    async_add_entities(ents)


class EnergyPlanModeSelect(AbbChargerEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "energy_plan_mode"
    _attr_icon = "mdi:cash-clock"
    _attr_options = list(ENERGY_PLAN_MODES)

    def __init__(self, coordinator):
        super().__init__(coordinator, "energy_plan_mode")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.energy_plan is not None

    @property
    def current_option(self) -> str | None:
        plan = self.coordinator.data.energy_plan
        if not plan:
            return None
        for name, value in ENERGY_PLAN_MODES.items():
            if value == plan.get("open"):
                return name
        return None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.async_update_energy_plan(open=ENERGY_PLAN_MODES[option])
        except AbbApiError as err:
            raise HomeAssistantError(f"Energy plan update failed: {err}") from err


class CurrencySelect(AbbChargerEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "currency"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator):
        super().__init__(coordinator, "currency")

    @property
    def available(self) -> bool:
        d = self.coordinator.data
        return super().available and d.energy_plan is not None and bool(d.currencies)

    @property
    def options(self) -> list[str]:
        return [self._label(c) for c in self.coordinator.data.currencies]

    @property
    def current_option(self) -> str | None:
        plan = self.coordinator.data.energy_plan
        if not plan:
            return None
        for c in self.coordinator.data.currencies:
            if c.get("currencyType") == plan.get("currencyType"):
                return self._label(c)
        return None

    async def async_select_option(self, option: str) -> None:
        for c in self.coordinator.data.currencies:
            if self._label(c) == option:
                try:
                    await self.coordinator.async_update_energy_plan(currencyType=c.get("currencyType"))
                except AbbApiError as err:
                    raise HomeAssistantError(f"Energy plan update failed: {err}") from err
                return
        raise HomeAssistantError(f"Unknown currency {option}")

    @staticmethod
    def _label(currency: dict) -> str:
        name = currency.get("name") or currency.get("tag") or str(currency.get("currencyType"))
        symbol = currency.get("symbol")
        return f"{name} ({symbol})" if symbol and symbol != name else str(name)
