"""Config flow for Tuya Peephole Camera integration.

Two-step flow:
1. Credentials: email + password + region → login → fetch device list
2. Device selection: pick camera from discovered devices → auto-fill device_id + local_key
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlowWithConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import TuyaSmartAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_LOCAL_KEY,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    REGION_NAMES,
    REGIONS,
)
from .exceptions import TuyaApiError, TuyaAuthError

_LOGGER = logging.getLogger(__name__)

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_REGION, default="eu"): vol.In(REGION_NAMES),
    }
)


class TuyaPeepholeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya Peephole Camera."""

    VERSION = 1
    _reauth_entry: ConfigEntry | None = None
    _api: TuyaSmartAPI | None = None
    _devices: list[dict[str, Any]] = []
    _credentials: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TuyaPeepholeOptionsFlow:
        """Create the options flow handler."""
        return TuyaPeepholeOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Collect credentials and login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._credentials = user_input
            region = user_input[CONF_REGION]

            try:
                session = async_create_clientsession(self.hass)
                self._api = TuyaSmartAPI(
                    session=session,
                    host=REGIONS[region],
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    country_code=region.upper(),
                )
                await self._api.async_login()
                self._devices = await self._api.async_get_device_list()
            except TuyaAuthError:
                errors["base"] = "invalid_auth"
            except TuyaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Select device from discovered list."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_id = user_input[CONF_DEVICE_ID]

            # Find selected device to get local_key
            device = next(
                (d for d in self._devices if d.get("id") == selected_id),
                None,
            )
            if device is None:
                errors["base"] = "device_not_found"
            else:
                await self.async_set_unique_id(selected_id)
                self._abort_if_unique_id_configured()

                local_key = device.get("localKey", "")
                device_name = device.get("name", selected_id)

                return self.async_create_entry(
                    title=f"Tuya Peephole {device_name}",
                    data={
                        CONF_EMAIL: self._credentials[CONF_EMAIL],
                        CONF_PASSWORD: self._credentials[CONF_PASSWORD],
                        CONF_REGION: self._credentials[CONF_REGION],
                        CONF_DEVICE_ID: selected_id,
                        CONF_LOCAL_KEY: local_key,
                    },
                )

        # Build device selector: show name + id for each device
        device_options = {
            d["id"]: f"{d.get('name', 'Unknown')} ({d['id'][:8]}...)"
            for d in self._devices
            if "id" in d
        }

        if not device_options:
            return self.async_abort(reason="no_devices")

        device_schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): vol.In(device_options),
            }
        )

        return self.async_show_form(
            step_id="device",
            data_schema=device_schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauth trigger from token refresh failure."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth confirmation — collect and validate new credentials."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            try:
                session = async_create_clientsession(self.hass)
                region = self._reauth_entry.data[CONF_REGION]
                api = TuyaSmartAPI(
                    session=session,
                    host=REGIONS[region],
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    country_code=region.upper(),
                )
                await api.async_login()
            except TuyaAuthError:
                errors["base"] = "invalid_auth"
            except TuyaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, **user_input},
                )
                return self.async_abort(reason="reauth_successful")

        existing = self._reauth_entry.data
        reauth_schema = vol.Schema(
            {
                vol.Required(
                    CONF_EMAIL, default=existing.get(CONF_EMAIL, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=reauth_schema,
            errors=errors,
        )


class TuyaPeepholeOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options flow for Tuya Peephole Camera."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial options step."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("recording_enabled", default=True): bool,
                        vol.Required(
                            "retention_days", default=7
                        ): vol.All(int, vol.Range(min=1, max=30)),
                        vol.Required(
                            "recording_duration", default=60
                        ): vol.All(int, vol.Range(min=10, max=300)),
                    }
                ),
                self.options,
            ),
        )
