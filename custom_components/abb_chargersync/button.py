"""Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AbbConfigEntry
from .api import AbbApiError
from .entity import AbbChargerEntity
from .services import current_month_range


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ents = []
    for c in entry.runtime_data.coordinators.values():
        ents += [StartButton(c), StopButton(c), MonthlyReportButton(c), ReconnectButton(c)]
    async_add_entities(ents)


class StartButton(AbbChargerEntity, ButtonEntity):
    _attr_translation_key = "start_charging"

    def __init__(self, coordinator):
        super().__init__(coordinator, "start")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_start_charging()
        except AbbApiError as err:
            raise HomeAssistantError(str(err)) from err


class StopButton(AbbChargerEntity, ButtonEntity):
    _attr_translation_key = "stop_charging"

    def __init__(self, coordinator):
        super().__init__(coordinator, "stop")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_stop_charging()
        except AbbApiError as err:
            raise HomeAssistantError(str(err)) from err


class MonthlyReportButton(AbbChargerEntity, ButtonEntity):
    """Ask ABB to e-mail a PDF report of this month's sessions to the account address."""

    _attr_translation_key = "monthly_report"
    _attr_icon = "mdi:file-pdf-box"

    def __init__(self, coordinator):
        super().__init__(coordinator, "monthly_report")

    async def async_press(self) -> None:
        start, end = current_month_range()
        try:
            await self.coordinator.async_request_report(start, end, fmt="pdf")
        except AbbApiError as err:
            raise HomeAssistantError(f"Report request failed: {err}") from err


class ReconnectButton(AbbChargerEntity, ButtonEntity):
    _attr_translation_key = "reconnect"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "reconnect")

    async def async_press(self) -> None:
        await self.coordinator.async_shutdown_relay()
        await self.coordinator.async_request_refresh()
