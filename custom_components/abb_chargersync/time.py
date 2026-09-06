"""Start and end time of the charger's daily charging window."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
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
            ents += [ScheduleTime(c, "start"), ScheduleTime(c, "end")]
        ents += [PeakTime(c, key) for key in PEAK_KEYS]
    async_add_entities(ents)


PEAK_KEYS = {
    "on_peak_start": "onPeakSt",
    "on_peak_end": "onPeakEt",
    "mid_peak_start": "midPeakSt",
    "mid_peak_end": "midPeakEt",
    "off_peak_start": "offPeakSt",
    "off_peak_end": "offPeakEt",
}


class ScheduleTime(AbbChargerEntity, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, bound: str) -> None:
        super().__init__(coordinator, f"schedule_{bound}")
        self._bound = bound
        self._attr_translation_key = f"schedule_{bound}"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.schedule is not None

    @property
    def native_value(self) -> time | None:
        if self.coordinator.data.schedule is None:
            return None
        start, end = self.coordinator.schedule_times
        return start if self._bound == "start" else end

    async def async_set_value(self, value: time) -> None:
        sched = self.coordinator.data.schedule
        enabled = bool(sched and sched.enabled)
        kwargs = {self._bound: value.replace(second=0, microsecond=0)}
        try:
            await self.coordinator.async_set_schedule(enabled, **kwargs)
        except AbbApiError as err:
            raise HomeAssistantError(f"Schedule change failed: {err}") from err


class PeakTime(AbbChargerEntity, TimeEntity):
    """Boundary of one tariff window of the cloud energy plan."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cash-clock"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._field = PEAK_KEYS[key]
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.energy_plan is not None

    @property
    def native_value(self) -> time | None:
        raw = (self.coordinator.data.energy_plan or {}).get(self._field)
        if not raw:
            return None
        try:
            hour, minute = str(raw).split(":")[:2]
            return time(int(hour), int(minute))
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        try:
            await self.coordinator.async_update_energy_plan(**{self._field: value.strftime("%H:%M")})
        except AbbApiError as err:
            raise HomeAssistantError(f"Energy plan update failed: {err}") from err
