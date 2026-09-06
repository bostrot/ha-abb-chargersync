"""ABB ChargerSync integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AbbApiError, AbbAuthError, AbbCloudClient, AbbRelayClient
from .const import CONF_SCAN_INTERVAL, CONF_USE_RELAY, DEFAULT_SCAN_INTERVAL, PLATFORMS
from .coordinator import AbbChargerCoordinator
from .services import async_setup_services


@dataclass
class AbbRuntimeData:
    cloud: AbbCloudClient
    coordinators: dict[int, AbbChargerCoordinator]


type AbbConfigEntry = ConfigEntry[AbbRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: AbbConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    cloud = AbbCloudClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await cloud.login()
        await cloud.get_user()
        devices = await cloud.get_devices()
    except AbbAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AbbApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    use_relay = entry.options.get(CONF_USE_RELAY, True)
    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinators: dict[int, AbbChargerCoordinator] = {}
    for dev in devices:
        relay = AbbRelayClient(session, cloud, dev["deviceNumber"], int(dev["id"])) if use_relay else None
        coord = AbbChargerCoordinator(hass, entry, cloud, relay, dev, interval)
        await coord.async_config_entry_first_refresh()
        coordinators[int(dev["id"])] = coord

    entry.runtime_data = AbbRuntimeData(cloud, coordinators)
    async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: AbbConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AbbConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    for coord in entry.runtime_data.coordinators.values():
        await coord.async_shutdown_relay()
    return ok
