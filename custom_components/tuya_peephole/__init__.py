"""Tuya Peephole Camera integration for Home Assistant.

Sets up the coordinator, forwards entity platforms (binary_sensor, button),
and manages token refresh and clean teardown.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import TuyaSmartAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_LOCAL_KEY,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    RECORDING_DURATION,
    REGIONS,
    RETENTION_DAYS,
    TOKEN_REFRESH_HOURS,
)
from .recorder import RecordingManager
from .coordinator import TuyaPeepholeCoordinator
from .exceptions import TuyaApiError, TuyaAuthError

_LOGGER = logging.getLogger(__name__)

TOKEN_REFRESH_INTERVAL = timedelta(hours=TOKEN_REFRESH_HOURS)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CAMERA, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Peephole Camera from a config entry.

    Creates an API client, performs a fresh login, and registers
    a 6-hour token refresh interval to keep the session alive.
    """
    session = async_create_clientsession(hass)
    region = entry.data[CONF_REGION]

    api = TuyaSmartAPI(
        session=session,
        host=REGIONS[region],
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        country_code=region.upper(),
    )

    # Fresh login on startup (don't persist sid/cookies across restarts)
    try:
        await api.async_login()
    except TuyaAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except TuyaApiError as err:
        raise ConfigEntryNotReady(f"Cannot connect to Tuya API: {err}") from err

    # Create coordinator (owns MQTT client lifecycle)
    coordinator = TuyaPeepholeCoordinator(
        hass, api, entry.data[CONF_DEVICE_ID], entry.data[CONF_LOCAL_KEY]
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward entity platforms (binary_sensor, button)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Proactive token refresh every 6 hours (before session expiry)
    async def _async_refresh_token(_now) -> None:
        """Re-login to refresh the Tuya session token."""
        try:
            await api.async_login()
            _LOGGER.debug("Tuya session refreshed successfully")
        except TuyaAuthError:
            _LOGGER.error(
                "Token refresh failed: authentication error, starting reauth"
            )
            entry.async_start_reauth(hass)
        except TuyaApiError as err:
            _LOGGER.warning(
                "Token refresh failed, will retry next interval: %s", err
            )

    unsub = async_track_time_interval(
        hass, _async_refresh_token, TOKEN_REFRESH_INTERVAL
    )
    entry.async_on_unload(unsub)

    # Set up recording manager
    recording_manager = RecordingManager(hass, coordinator)
    await recording_manager.async_setup()

    # Apply options if already configured
    options = entry.options
    if options:
        recording_manager.update_options(
            retention_days=options.get("retention_days", RETENTION_DAYS),
            duration=options.get("recording_duration", RECORDING_DURATION),
            enabled=options.get("recording_enabled", True),
        )

    # Store recording manager alongside coordinator
    hass.data[DOMAIN][f"{entry.entry_id}_recorder"] = recording_manager

    # Listen for options changes
    async def _async_options_updated(
        hass_ref: HomeAssistant, entry_ref: ConfigEntry
    ) -> None:
        """Update recording manager when options change."""
        rec_mgr: RecordingManager | None = hass_ref.data.get(DOMAIN, {}).get(
            f"{entry_ref.entry_id}_recorder"
        )
        if rec_mgr is not None:
            rec_mgr.update_options(
                retention_days=entry_ref.options.get(
                    "retention_days", RETENTION_DAYS
                ),
                duration=entry_ref.options.get(
                    "recording_duration", RECORDING_DURATION
                ),
                enabled=entry_ref.options.get("recording_enabled", True),
            )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Monitor charging state for continuous recording
    async def _on_coordinator_update() -> None:
        """Start/stop continuous recording based on charging state."""
        rec_mgr: RecordingManager | None = hass.data.get(DOMAIN, {}).get(
            f"{entry.entry_id}_recorder"
        )
        if rec_mgr is None:
            return
        if coordinator.is_charging:
            await rec_mgr.async_start_continuous()
        else:
            await rec_mgr.async_stop_continuous()

    entry.async_on_unload(
        coordinator.async_add_listener(_on_coordinator_update)
    )

    _LOGGER.info(
        "Tuya Peephole integration set up for device %s",
        entry.data[CONF_DEVICE_ID],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Tuya Peephole Camera config entry.

    Unloads entity platforms, tears down the coordinator (disconnects MQTT),
    and removes stored data. The token refresh timer is cleaned up
    automatically via entry.async_on_unload.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        # Tear down recording manager first
        recording_manager: RecordingManager | None = hass.data[DOMAIN].pop(
            f"{entry.entry_id}_recorder", None
        )
        if recording_manager is not None:
            await recording_manager.async_teardown()

        coordinator: TuyaPeepholeCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_teardown()
    return unload_ok
