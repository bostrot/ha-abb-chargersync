"""Config flow for ABB ChargerSync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AbbApiError, AbbAuthError, AbbCloudClient
from .const import CONF_SCAN_INTERVAL, CONF_USE_RELAY, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AbbConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def _validate(self, email: str, password: str) -> dict[str, str]:
        cloud = AbbCloudClient(async_get_clientsession(self.hass), email, password)
        try:
            await cloud.login()
            await cloud.get_user()
            devices = await cloud.get_devices()
        except AbbAuthError:
            return {"base": "invalid_auth"}
        except AbbApiError:
            return {"base": "cannot_connect"}
        if not devices:
            return {"base": "no_devices"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            errors = await self._validate(email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=f"ABB ChargerSync ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            errors = await self._validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AbbOptionsFlow()


class AbbOptionsFlow(OptionsFlow):
    """Options: polling interval and relay usage."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
                vol.Optional(CONF_USE_RELAY, default=opts.get(CONF_USE_RELAY, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
