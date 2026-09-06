"""Sensors for ABB chargers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .coordinator import AbbChargerCoordinator, ChargerData
from .entity import AbbChargerEntity
from .protocol import STATUS_NAMES


@dataclass(frozen=True, kw_only=True)
class AbbSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ChargerData], Any]
    available_fn: Callable[[ChargerData], bool] = lambda d: d.status is not None


def _st(attr: str, default: Any = None) -> Callable[[ChargerData], Any]:
    return lambda d: getattr(d.status, attr, default) if d.status else default


SENSORS: tuple[AbbSensorDescription, ...] = (
    AbbSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(STATUS_NAMES.values()) | {"unknown"}),
        value_fn=lambda d: d.status.status if d.status and d.status.status in STATUS_NAMES.values() else "unknown",
    ),
    AbbSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.status.power_w if d.status else None,
    ),
    AbbSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_st("energy_kwh", 0.0),
    ),
    AbbSensorDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_st("duration_s", 0),
    ),
    AbbSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_st("current_l1", 0.0),
    ),
    AbbSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        value_fn=_st("current_l2", 0.0),
    ),
    AbbSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        value_fn=_st("current_l3", 0.0),
    ),
    AbbSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=_st("voltage_l1", 0.0),
    ),
    AbbSensorDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
        value_fn=_st("voltage_l2", 0.0),
    ),
    AbbSensorDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
        value_fn=_st("voltage_l3", 0.0),
    ),
    AbbSensorDescription(
        key="rated_current",
        translation_key="rated_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.status.rated_current if d.status and d.status.rated_current else d.device.get("ratedCurrent")),
        available_fn=lambda d: True,
    ),
    AbbSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_st("fault_code", 0),
    ),
    AbbSensorDescription(
        key="max_current_limit",
        translation_key="max_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.power.max_output_current if d.power else None,
        available_fn=lambda d: d.power is not None,
    ),
    AbbSensorDescription(
        key="relay_error",
        translation_key="relay_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.relay_error or "ok",
        available_fn=lambda d: True,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entities: list[AbbSensor] = []
    for coord in entry.runtime_data.coordinators.values():
        entities.extend(AbbSensor(coord, desc) for desc in SENSORS)
    async_add_entities(entities)


class AbbSensor(AbbChargerEntity, SensorEntity):
    entity_description: AbbSensorDescription

    def __init__(self, coordinator: AbbChargerCoordinator, description: AbbSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.coordinator.data)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "status":
            d = self.coordinator.data
            return {
                "status_code": d.status.status_code if d.status else None,
                "cloud_status": d.device.get("status"),
                "session_id": d.status.session_id if d.status else None,
                "phase_type": d.status.phase_type if d.status else None,
            }
        return None
