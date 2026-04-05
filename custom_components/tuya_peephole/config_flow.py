"""Config flow for Tuya Peephole Camera integration."""

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

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_REGION, default="eu"): vol.In(REGION_NAMES),
    }
)


class TuyaPeepholeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya Peephole Camera."""

    VERSION = 1
    _reauth_entry: ConfigEntry | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TuyaPeepholeOptionsFlow:
        """Create the options flow handler."""
        return TuyaPeepholeOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step -- collect credentials and validate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Set unique ID to device_id (one device = one config entry)
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            # Validate credentials by attempting a full login
            try:
                session = async_create_clientsession(self.hass)
                region = user_input[CONF_REGION]
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
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Tuya Peephole {user_input[CONF_DEVICE_ID]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauth trigger from token refresh failure.

        Stores the config entry reference and proceeds to the
        reauth_confirm step where the user provides updated credentials.
        """
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth confirmation -- collect and validate new credentials.

        Shows a form pre-filled with email and local_key from the existing
        entry. On successful login, updates the config entry data and aborts
        with reauth_successful.
        """
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

        # Pre-fill email and local_key from existing entry
        existing = self._reauth_entry.data
        reauth_schema = vol.Schema(
            {
                vol.Required(
                    CONF_EMAIL, default=existing.get(CONF_EMAIL, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(
                    CONF_LOCAL_KEY,
                    default=existing.get(CONF_LOCAL_KEY, ""),
                ): str,
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
