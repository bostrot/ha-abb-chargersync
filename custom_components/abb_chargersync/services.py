"""Services for the ABB ChargerSync integration."""

from __future__ import annotations

from datetime import date

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import AbbApiError
from .const import (
    ATTR_COMPANY_ONLY,
    ATTR_EMAIL,
    ATTR_END_DATE,
    ATTR_FORMAT,
    ATTR_START_DATE,
    DOMAIN,
    REPORT_FORMATS,
    SERVICE_REQUEST_REPORT,
)
from .coordinator import AbbChargerCoordinator

REQUEST_REPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_START_DATE): cv.date,
        vol.Optional(ATTR_END_DATE): cv.date,
        vol.Optional(ATTR_FORMAT, default="pdf"): vol.In(REPORT_FORMATS),
        vol.Optional(ATTR_EMAIL): vol.Email(),
        vol.Optional(ATTR_COMPANY_ONLY): cv.boolean,
    }
)


def current_month_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return today.replace(day=1), today


def coordinator_for_device(hass: HomeAssistant, device_id: str) -> AbbChargerCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device {device_id}")
    device_numbers = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
            continue
        for coordinator in entry.runtime_data.coordinators.values():
            if coordinator.device_number in device_numbers:
                return coordinator
    raise ServiceValidationError(f"Device {device_id} is not an ABB charger")


async def _request_report(call: ServiceCall) -> ServiceResponse:
    coordinator = coordinator_for_device(call.hass, call.data[ATTR_DEVICE_ID])
    default_start, default_end = current_month_range()
    start = call.data.get(ATTR_START_DATE, default_start)
    end = call.data.get(ATTR_END_DATE, default_end)
    if end < start:
        raise ServiceValidationError("end_date must not be before start_date")
    try:
        recipient = await coordinator.async_request_report(
            start,
            end,
            fmt=call.data[ATTR_FORMAT],
            email=call.data.get(ATTR_EMAIL),
            company_only=call.data.get(ATTR_COMPANY_ONLY),
        )
    except AbbApiError as err:
        raise HomeAssistantError(f"Report request failed: {err}") from err
    return {
        "device_number": coordinator.device_number,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "format": call.data[ATTR_FORMAT],
        "sent_to": recipient,
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REQUEST_REPORT):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_REPORT,
        _request_report,
        schema=REQUEST_REPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
