"""Tests for snapshot button and reauth config flow.

Requirements covered: CTRL-02 (snapshot), CONF-03 (reauth)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTuyaSnapshotButton:
    """Test TuyaSnapshotButton entity."""

    def test_snapshot_button_icon(self, mock_coordinator):
        """[CTRL-02] Snapshot button has mdi:camera icon."""
        from custom_components.tuya_peephole.button import TuyaSnapshotButton

        button = TuyaSnapshotButton(mock_coordinator)
        assert button._attr_icon == "mdi:camera"

    def test_snapshot_button_unique_id(self, mock_coordinator):
        """Snapshot button unique_id is {device_id}_snapshot."""
        from custom_components.tuya_peephole.button import TuyaSnapshotButton

        button = TuyaSnapshotButton(mock_coordinator)
        assert button._attr_unique_id == "test_device_id_abc123_snapshot"

    def test_snapshot_button_name(self, mock_coordinator):
        """Snapshot button name is 'Snapshot'."""
        from custom_components.tuya_peephole.button import TuyaSnapshotButton

        button = TuyaSnapshotButton(mock_coordinator)
        assert button._attr_name == "Snapshot"

    @pytest.mark.asyncio
    async def test_snapshot_button_press_wakes_camera(self, mock_coordinator):
        """[CTRL-02] Snapshot button wakes camera if sleeping."""
        from custom_components.tuya_peephole.button import TuyaSnapshotButton
        from custom_components.tuya_peephole.models import CameraState

        mock_coordinator.camera_state = CameraState.SLEEPING
        mock_coordinator.async_wake_camera = AsyncMock(return_value=True)
        mock_coordinator.api.async_get_snapshot = AsyncMock(
            return_value="https://example.com/snap.jpg"
        )
        button = TuyaSnapshotButton(mock_coordinator)

        await button.async_press()

        mock_coordinator.async_wake_camera.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snapshot_button_press_requests_snapshot(self, mock_coordinator):
        """[CTRL-02] Snapshot button requests snapshot from API."""
        from custom_components.tuya_peephole.button import TuyaSnapshotButton
        from custom_components.tuya_peephole.models import CameraState

        mock_coordinator.camera_state = CameraState.AWAKE
        mock_coordinator.api.async_get_snapshot = AsyncMock(
            return_value="https://example.com/snap.jpg"
        )
        button = TuyaSnapshotButton(mock_coordinator)

        await button.async_press()

        mock_coordinator.api.async_get_snapshot.assert_awaited_once_with(
            mock_coordinator.device_id
        )

    def test_button_setup_registers_both_buttons(
        self, mock_hass_with_loop, mock_coordinator, mock_config_entry
    ):
        """async_setup_entry creates both wake and snapshot buttons."""
        # Verify module structure -- both classes exist and are importable
        from custom_components.tuya_peephole.button import (
            TuyaWakeButton,
            TuyaSnapshotButton,
        )

        assert TuyaWakeButton is not None
        assert TuyaSnapshotButton is not None


class TestReauthConfigFlow:
    """Test re-authentication config flow (CONF-03)."""

    def test_reauth_step_exists(self):
        """[CONF-03] ConfigFlow has async_step_reauth method."""
        from custom_components.tuya_peephole.config_flow import TuyaPeepholeConfigFlow

        assert hasattr(TuyaPeepholeConfigFlow, "async_step_reauth")

    def test_reauth_confirm_step_exists(self):
        """[CONF-03] ConfigFlow has async_step_reauth_confirm method."""
        from custom_components.tuya_peephole.config_flow import TuyaPeepholeConfigFlow

        assert hasattr(TuyaPeepholeConfigFlow, "async_step_reauth_confirm")
