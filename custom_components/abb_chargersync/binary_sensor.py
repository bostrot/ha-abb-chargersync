"""Binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ents = []
    for coord in entry.runtime_data.coordinators.values():
        ents += [OnlineSensor(coord), ChargingSensor(coord), PluggedSensor(coord)]
    async_add_entities(ents)


class OnlineSensor(AbbChargerEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "online"

    def __init__(self, coordinator):
        super().__init__(coordinator, "online")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d.relay_online or d.device.get("online"))


class ChargingSensor(AbbChargerEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_translation_key = "charging"

    def __init__(self, coordinator):
        super().__init__(coordinator, "charging")

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data.status is not None or self.coordinator.data.active_session is not None)

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        if d.status:
            return d.status.charging
        return d.active_session is not None


class PluggedSensor(AbbChargerEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_translation_key = "plugged_in"

    def __init__(self, coordinator):
        super().__init__(coordinator, "plugged_in")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.status is not None

    @property
    def is_on(self) -> bool:
        st = self.coordinator.data.status
        return st is not None and 1 <= st.status_code <= 8
