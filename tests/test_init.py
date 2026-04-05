"""Tests for tuya_peephole __init__.py (async_setup_entry, async_unload_entry).

Tests the integration entry point: login on startup, coordinator creation,
platform forwarding, token refresh registration, auth failure handling,
and clean unload with teardown.

Requirements covered: AUTH-01, AUTH-02, REL-01, REL-02, REL-03
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuya_peephole.const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    TOKEN_REFRESH_HOURS,
)
from custom_components.tuya_peephole.exceptions import TuyaApiError, TuyaAuthError


def _get_setup_entry():
    """Import async_setup_entry from __init__.py."""
    from custom_components.tuya_peephole import async_setup_entry

    return async_setup_entry


def _get_unload_entry():
    """Import async_unload_entry from __init__.py."""
    from custom_components.tuya_peephole import async_unload_entry

    return async_unload_entry


def _make_mock_coordinator():
    """Create a mock coordinator for patching."""
    mock_coord = MagicMock()
    mock_coord.async_config_entry_first_refresh = AsyncMock()
    mock_coord.async_teardown = AsyncMock()
    mock_coord.is_charging = False
    mock_coord.async_add_listener = MagicMock(return_value=MagicMock())
    return mock_coord


def _make_mock_recording_manager():
    """Create a mock RecordingManager for patching."""
    mock_rm = MagicMock()
    mock_rm.async_setup = AsyncMock()
    mock_rm.async_teardown = AsyncMock()
    mock_rm.update_options = MagicMock()
    mock_rm.async_start_continuous = AsyncMock()
    mock_rm.async_stop_continuous = AsyncMock()
    return mock_rm


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_setup_entry_success(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """[AUTH-01] Successful login stores coordinator in hass.data and returns True."""
        setup_entry = _get_setup_entry()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})
        mock_coord = _make_mock_coordinator()
        mock_rm = _make_mock_recording_manager()

        mock_unsub = MagicMock()

        with (
            patch(
                "custom_components.tuya_peephole.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.TuyaSmartAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.tuya_peephole.TuyaPeepholeCoordinator",
                return_value=mock_coord,
            ),
            patch(
                "custom_components.tuya_peephole.async_track_time_interval",
                return_value=mock_unsub,
            ),
            patch(
                "custom_components.tuya_peephole.RecordingManager",
                return_value=mock_rm,
            ),
        ):
            result = await setup_entry(mock_hass, mock_config_entry)

        assert result is True
        assert DOMAIN in mock_hass.data
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]
        assert mock_hass.data[DOMAIN][mock_config_entry.entry_id] is mock_coord
        mock_api.async_login.assert_awaited_once()
        mock_coord.async_config_entry_first_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setup_entry_registers_token_refresh(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """[AUTH-02] Setup registers a periodic token refresh callback."""
        setup_entry = _get_setup_entry()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})
        mock_coord = _make_mock_coordinator()
        mock_rm = _make_mock_recording_manager()

        mock_unsub = MagicMock()

        with (
            patch(
                "custom_components.tuya_peephole.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.TuyaSmartAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.tuya_peephole.TuyaPeepholeCoordinator",
                return_value=mock_coord,
            ),
            patch(
                "custom_components.tuya_peephole.async_track_time_interval",
                return_value=mock_unsub,
            ) as mock_track,
            patch(
                "custom_components.tuya_peephole.RecordingManager",
                return_value=mock_rm,
            ),
        ):
            await setup_entry(mock_hass, mock_config_entry)

        # async_track_time_interval should be called with the hass, callback, and interval
        mock_track.assert_called_once()
        call_args = mock_track.call_args
        # First positional arg is hass
        assert call_args[0][0] is mock_hass
        # Third positional arg (or kwarg) is the interval -- should be TOKEN_REFRESH_HOURS
        interval = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("interval")
        assert interval == timedelta(hours=TOKEN_REFRESH_HOURS)

    @pytest.mark.asyncio
    async def test_setup_entry_registers_unload_callback(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """Setup registers unsub via entry.async_on_unload."""
        setup_entry = _get_setup_entry()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})
        mock_coord = _make_mock_coordinator()
        mock_rm = _make_mock_recording_manager()

        mock_unsub = MagicMock()

        with (
            patch(
                "custom_components.tuya_peephole.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.TuyaSmartAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.tuya_peephole.TuyaPeepholeCoordinator",
                return_value=mock_coord,
            ),
            patch(
                "custom_components.tuya_peephole.async_track_time_interval",
                return_value=mock_unsub,
            ),
            patch(
                "custom_components.tuya_peephole.RecordingManager",
                return_value=mock_rm,
            ),
        ):
            await setup_entry(mock_hass, mock_config_entry)

        # async_on_unload should have been called with the unsub callable
        assert mock_unsub in mock_config_entry._on_unload_callbacks

    @pytest.mark.asyncio
    async def test_setup_entry_auth_failed(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """[REL-02] TuyaAuthError during login raises ConfigEntryAuthFailed."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        setup_entry = _get_setup_entry()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(
            side_effect=TuyaAuthError("wrong password")
        )

        with (
            patch(
                "custom_components.tuya_peephole.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            with pytest.raises(ConfigEntryAuthFailed):
                await setup_entry(mock_hass, mock_config_entry)

    @pytest.mark.asyncio
    async def test_setup_entry_not_ready(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """[REL-03] TuyaApiError during login raises ConfigEntryNotReady."""
        from homeassistant.exceptions import ConfigEntryNotReady

        setup_entry = _get_setup_entry()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(
            side_effect=TuyaApiError("network timeout")
        )

        with (
            patch(
                "custom_components.tuya_peephole.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            with pytest.raises(ConfigEntryNotReady):
                await setup_entry(mock_hass, mock_config_entry)


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    @pytest.mark.asyncio
    async def test_unload_entry_removes_data(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """Unload removes the entry, tears down coordinator, and unloads platforms."""
        unload_entry = _get_unload_entry()

        mock_coord = _make_mock_coordinator()
        mock_rm = _make_mock_recording_manager()

        # Set up hass.data as if setup had run (coordinator + recorder pattern)
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: mock_coord,
            f"{mock_config_entry.entry_id}_recorder": mock_rm,
        }
        # Mock async_unload_platforms to return True
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        result = await unload_entry(mock_hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]
        mock_coord.async_teardown.assert_awaited_once()
        mock_rm.async_teardown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unload_entry_platform_unload_fails(
        self, mock_hass: MagicMock, mock_config_entry: object
    ) -> None:
        """Unload returns False when platform unload fails, coordinator not torn down."""
        unload_entry = _get_unload_entry()

        mock_coord = _make_mock_coordinator()
        mock_rm = _make_mock_recording_manager()

        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: mock_coord,
            f"{mock_config_entry.entry_id}_recorder": mock_rm,
        }
        # Mock async_unload_platforms to return False
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        result = await unload_entry(mock_hass, mock_config_entry)

        assert result is False
        # Coordinator should NOT be torn down if platforms failed to unload
        mock_coord.async_teardown.assert_not_awaited()
        mock_rm.async_teardown.assert_not_awaited()
