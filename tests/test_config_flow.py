"""Tests for TuyaPeepholeConfigFlow.

Tests the config flow UI: user step, credential validation, error handling,
and duplicate device detection. Since config_flow.py may not exist yet
(Plan 01-02 runs in parallel), tests are written against the planned
interface from 01-02-PLAN.md.

Requirements covered: CONF-01, CONF-02
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuya_peephole.const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    REGIONS,
    REGION_NAMES,
)
from custom_components.tuya_peephole.exceptions import TuyaApiError, TuyaAuthError


def _get_config_flow_class():
    """Import and return TuyaPeepholeConfigFlow.

    Deferred import so conftest.py mocks are applied first.
    """
    from custom_components.tuya_peephole.config_flow import TuyaPeepholeConfigFlow

    return TuyaPeepholeConfigFlow


class TestConfigFlowUserStep:
    """Test the user step of the config flow."""

    @pytest.mark.asyncio
    async def test_user_step_shows_form_on_none_input(self) -> None:
        """[CONF-01] Initial call with no input shows the form."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_user_step_creates_entry_on_success(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-01] Successful login creates a config entry."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            result = await flow.async_step_user(user_input=mock_config_entry_data)

        assert result["type"] == "create_entry"
        assert result["data"] == mock_config_entry_data
        assert mock_config_entry_data[CONF_DEVICE_ID] in result["title"]

    @pytest.mark.asyncio
    async def test_user_step_invalid_auth_error(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-02] TuyaAuthError shows invalid_auth error."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(side_effect=TuyaAuthError("wrong password"))

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            result = await flow.async_step_user(user_input=mock_config_entry_data)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_user_step_cannot_connect_error(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-02] TuyaApiError shows cannot_connect error."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(side_effect=TuyaApiError("network error"))

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            result = await flow.async_step_user(user_input=mock_config_entry_data)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_user_step_unknown_error(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-02] Unexpected exception shows unknown error."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(side_effect=RuntimeError("unexpected"))

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            result = await flow.async_step_user(user_input=mock_config_entry_data)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "unknown"

    @pytest.mark.asyncio
    async def test_user_step_sets_unique_id(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-01] Config flow sets unique_id to device_id."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            await flow.async_step_user(user_input=mock_config_entry_data)

        assert flow._unique_id == mock_config_entry_data[CONF_DEVICE_ID]

    @pytest.mark.asyncio
    async def test_user_step_already_configured(
        self, mock_config_entry_data: dict
    ) -> None:
        """[CONF-01] Duplicate device_id aborts with already_configured."""
        flow_cls = _get_config_flow_class()
        flow = flow_cls()
        flow.hass = MagicMock()

        # Override _abort_if_unique_id_configured to simulate HA's behavior
        from homeassistant.data_entry_flow import FlowResult

        def raise_abort() -> None:
            raise _AbortFlow("already_configured")

        class _AbortFlow(Exception):
            def __init__(self, reason: str) -> None:
                self.reason = reason
                super().__init__(reason)

        # Patch the flow to simulate abort
        original_abort = flow._abort_if_unique_id_configured

        def mock_abort_if_configured() -> None:
            # Simulate HA raising abort when unique ID is already configured
            raise _AbortFlow("already_configured")

        flow._abort_if_unique_id_configured = mock_abort_if_configured

        mock_api = MagicMock()
        mock_api.async_login = AsyncMock(return_value={"sid": "test_sid"})

        with (
            patch(
                "custom_components.tuya_peephole.config_flow.async_create_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.tuya_peephole.config_flow.TuyaSmartAPI",
                return_value=mock_api,
            ),
        ):
            with pytest.raises(_AbortFlow, match="already_configured"):
                await flow.async_step_user(user_input=mock_config_entry_data)


class TestConfigFlowStructure:
    """Test config flow class structure and imports."""

    def test_config_flow_class_exists(self) -> None:
        """Config flow class can be imported."""
        flow_cls = _get_config_flow_class()
        assert flow_cls is not None

    def test_config_flow_has_version(self) -> None:
        """Config flow declares VERSION = 1."""
        flow_cls = _get_config_flow_class()
        assert hasattr(flow_cls, "VERSION")
        assert flow_cls.VERSION == 1

    def test_config_flow_has_user_step(self) -> None:
        """Config flow has async_step_user method."""
        flow_cls = _get_config_flow_class()
        assert hasattr(flow_cls, "async_step_user")

    def test_config_flow_uses_region_names(self) -> None:
        """Config flow schema uses REGION_NAMES for friendly dropdown."""
        import inspect

        from custom_components.tuya_peephole import config_flow

        source = inspect.getsource(config_flow)
        assert "REGION_NAMES" in source, "Config flow must use REGION_NAMES for dropdown"
