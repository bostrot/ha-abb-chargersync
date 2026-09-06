"""Firmware update entity fed by the ChargerSync cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .entity import AbbChargerEntity


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(FirmwareUpdate(c) for c in entry.runtime_data.coordinators.values())


class FirmwareUpdate(AbbChargerEntity, UpdateEntity):
    """Shows the charger firmware and the version ABB offers for it.

    Installing is not offered: the ChargerSync app only flashes firmware over a
    direct Bluetooth connection, never through the cloud relay this integration uses.
    """

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature(0)
    _attr_translation_key = "firmware"

    def __init__(self, coordinator):
        super().__init__(coordinator, "firmware")

    @property
    def installed_version(self) -> str | None:
        d = self.coordinator.data
        return d.firmware or d.device.get("softVersion") or None

    @property
    def _package(self) -> dict[str, Any] | None:
        rule = self.coordinator.data.firmware_rule
        if rule and rule.get("ruleIsForUpdate") is not False:
            return {"version": rule.get("version"), **(rule.get("packageInfo") or {})}
        newest = None
        for pkg in self.coordinator.data.firmware_packages:
            version = pkg.get("softVersion") or pkg.get("applyVersion")
            if version and (newest is None or _version_key(version) > _version_key(newest["version"])):
                newest = {"version": version, **pkg}
        return newest

    @property
    def latest_version(self) -> str | None:
        pkg = self._package
        if pkg and pkg.get("version"):
            return str(pkg["version"])
        return self.installed_version

    @property
    def title(self) -> str | None:
        pkg = self._package
        return (pkg or {}).get("name") or None

    @property
    def release_summary(self) -> str | None:
        pkg = self._package
        if not pkg:
            return None
        details = pkg.get("featureDetails")
        if isinstance(details, list):
            details = "\n".join(f"- {line}" for line in details if line)
        lines = []
        if details:
            lines.append(str(details))
        if pkg.get("isMandatory"):
            lines.append("ABB marks this update as mandatory.")
        lines.append("Install with the ChargerSync app over Bluetooth; the cloud relay cannot flash firmware.")
        return "\n\n".join(lines)[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pkg = self._package or {}
        return {
            "hardware_version": self.coordinator.data.hardware or self.coordinator.data.device.get("hardwareVersion"),
            "mandatory": pkg.get("isMandatory"),
            "checksum": pkg.get("checksum"),
        }


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for piece in str(version).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
