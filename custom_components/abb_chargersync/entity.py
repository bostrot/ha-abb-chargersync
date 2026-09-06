"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AbbChargerCoordinator


class AbbChargerEntity(CoordinatorEntity[AbbChargerCoordinator]):
    """Common device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AbbChargerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_number}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.coordinator.data.device
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_number)},
            manufacturer=MANUFACTURER,
            model=dev.get("model") or dev.get("hardwareModel") or "Terra AC",
            name=dev.get("aliasNumber") or self.coordinator.device_number,
            serial_number=self.coordinator.device_number,
            sw_version=self.coordinator.data.firmware or dev.get("softVersion"),
            hw_version=self.coordinator.data.hardware or dev.get("hardwareVersion"),
        )
