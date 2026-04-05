"""Tests for TuyaSmartAPI async client."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# These imports will fail until api.py is created (TDD RED)
from custom_components.tuya_peephole.api import TuyaSmartAPI
from custom_components.tuya_peephole.const import API_TIMEOUT, MQTT_WEBRTC_CACHE_TTL
from custom_components.tuya_peephole.exceptions import TuyaApiError, TuyaAuthError


def _make_api(session: aiohttp.ClientSession | None = None) -> TuyaSmartAPI:
    """Create a TuyaSmartAPI instance with test credentials."""
    mock_session = session or MagicMock(spec=aiohttp.ClientSession)
    return TuyaSmartAPI(
        session=mock_session,
        host="protect-eu.ismartlife.me",
        email="test@example.com",
        password="testpass",
        country_code="EU",
    )


def _mock_post_responses(api: TuyaSmartAPI, responses: list[dict]) -> None:
    """Patch _post to return a sequence of responses."""
    call_count = 0

    async def mock_post(path: str, data: dict) -> dict:
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        if not resp.get("success"):
            error_code = resp.get("errorCode", "unknown")
            error_msg = resp.get("errorMsg", str(resp))
            if error_code in ("USER_PASSWD_WRONG", "USER_NOT_EXISTS"):
                raise TuyaAuthError(f"Authentication failed: {error_msg}")
            raise TuyaApiError(f"API error {error_code}: {error_msg}")
        return resp

    api._post = mock_post  # type: ignore[method-assign]


class TestTuyaSmartAPIInit:
    """Test TuyaSmartAPI constructor."""

    def test_stores_session(self) -> None:
        """Session is stored as private attribute."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        api = TuyaSmartAPI(
            session=mock_session,
            host="test.example.com",
            email="test@example.com",
            password="testpass",
        )
        assert api._session is mock_session

    def test_default_country_code(self) -> None:
        """Country code defaults to EU."""
        api = _make_api()
        assert api._country_code == "EU"

    def test_initial_state_is_none(self) -> None:
        """sid, uid, mqtt_url start as None."""
        api = _make_api()
        assert api.sid is None
        assert api.uid is None
        assert api.mqtt_url is None

    def test_has_login_lock(self) -> None:
        """Login lock is an asyncio.Lock instance."""
        api = _make_api()
        assert isinstance(api._login_lock, asyncio.Lock)

    def test_cache_starts_empty(self) -> None:
        """WebRTC and MQTT caches start as None."""
        api = _make_api()
        assert api._webrtc_cache is None
        assert api._mqtt_cache is None


class TestPost:
    """Test the internal _post method."""

    @pytest.mark.asyncio
    async def test_post_raises_tuya_api_error_on_client_error(self) -> None:
        """ClientError is caught and re-raised as TuyaApiError."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("connection refused"))
        api = TuyaSmartAPI(
            session=mock_session,
            host="protect-eu.ismartlife.me",
            email="test@example.com",
            password="testpass",
        )
        with pytest.raises(TuyaApiError, match="API request failed"):
            await api._post("/api/test", {"key": "value"})

    @pytest.mark.asyncio
    async def test_post_raises_tuya_api_error_on_timeout(self) -> None:
        """TimeoutError is caught and re-raised as TuyaApiError."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.post = MagicMock(side_effect=TimeoutError("timed out"))
        api = TuyaSmartAPI(
            session=mock_session,
            host="protect-eu.ismartlife.me",
            email="test@example.com",
            password="testpass",
        )
        with pytest.raises(TuyaApiError, match="timed out"):
            await api._post("/api/test", {"key": "value"})

    @pytest.mark.asyncio
    async def test_post_raises_tuya_auth_error_on_wrong_password(
        self, auth_error_response: dict
    ) -> None:
        """USER_PASSWD_WRONG error code raises TuyaAuthError."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=auth_error_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.post = MagicMock(return_value=mock_response)

        api = TuyaSmartAPI(
            session=mock_session,
            host="protect-eu.ismartlife.me",
            email="test@example.com",
            password="testpass",
        )
        with pytest.raises(TuyaAuthError, match="Authentication failed"):
            await api._post("/api/test", {})

    @pytest.mark.asyncio
    async def test_post_raises_tuya_api_error_on_generic_error(
        self, api_error_response: dict
    ) -> None:
        """Non-auth error code raises TuyaApiError."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=api_error_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.post = MagicMock(return_value=mock_response)

        api = TuyaSmartAPI(
            session=mock_session,
            host="protect-eu.ismartlife.me",
            email="test@example.com",
            password="testpass",
        )
        with pytest.raises(TuyaApiError, match="SYSTEM_ERROR"):
            await api._post("/api/test", {})


class TestAsyncLogin:
    """Test async_login method."""

    @pytest.mark.asyncio
    async def test_login_sets_sid_uid_mqtt_url(
        self, token_response: dict, login_response: dict
    ) -> None:
        """Successful login sets sid, uid, and mqtt_url."""
        api = _make_api()
        _mock_post_responses(api, [token_response, login_response])

        result = await api.async_login()

        assert api.sid == "test_sid_abc"
        assert api.uid == "test_uid_def"
        assert api.mqtt_url == "m1-eu.iot334.com"
        assert result["sid"] == "test_sid_abc"

    @pytest.mark.asyncio
    async def test_login_raises_auth_error_on_bad_credentials(
        self, auth_error_response: dict
    ) -> None:
        """Login raises TuyaAuthError for wrong credentials."""
        api = _make_api()
        _mock_post_responses(api, [auth_error_response])

        with pytest.raises(TuyaAuthError):
            await api.async_login()

    @pytest.mark.asyncio
    async def test_login_uses_lock(
        self, token_response: dict, login_response: dict
    ) -> None:
        """Login acquires the login lock."""
        api = _make_api()
        _mock_post_responses(api, [token_response, login_response])

        # Verify the lock exists and is not locked before login
        assert not api._login_lock.locked()
        await api.async_login()
        # Lock should be released after login
        assert not api._login_lock.locked()


class TestAsyncGetWebrtcConfig:
    """Test async_get_webrtc_config method."""

    @pytest.mark.asyncio
    async def test_returns_webrtc_config(self, webrtc_config_response: dict) -> None:
        """Returns the result dict from /api/jarvis/config."""
        api = _make_api()
        _mock_post_responses(api, [webrtc_config_response])

        result = await api.async_get_webrtc_config("test_device_id")

        assert result["motoId"] == "test_moto_123"
        assert result["auth"] == "test_auth_token"
        assert result["skill"] == "webRTC"

    @pytest.mark.asyncio
    async def test_caches_webrtc_config(self, webrtc_config_response: dict) -> None:
        """Second call returns cached result without hitting API."""
        api = _make_api()
        call_count = 0
        original_resp = webrtc_config_response

        async def counting_post(path: str, data: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return original_resp

        api._post = counting_post  # type: ignore[method-assign]

        await api.async_get_webrtc_config("test_device_id")
        await api.async_get_webrtc_config("test_device_id")

        assert call_count == 1  # Only one API call, second was cached

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, webrtc_config_response: dict) -> None:
        """Cache expires after MQTT_WEBRTC_CACHE_TTL seconds."""
        api = _make_api()

        async def mock_post(path: str, data: dict) -> dict:
            return webrtc_config_response

        api._post = mock_post  # type: ignore[method-assign]

        await api.async_get_webrtc_config("test_device_id")

        # Simulate cache expiry
        api._webrtc_cache_time = time.time() - MQTT_WEBRTC_CACHE_TTL - 1

        call_count = 0
        original_post = api._post

        async def counting_post(path: str, data: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return await original_post(path, data)

        api._post = counting_post  # type: ignore[method-assign]

        await api.async_get_webrtc_config("test_device_id")
        assert call_count == 1  # Cache expired, new API call made


class TestAsyncGetMqttConfig:
    """Test async_get_mqtt_config method."""

    @pytest.mark.asyncio
    async def test_returns_mqtt_config(self, mqtt_config_response: dict) -> None:
        """Returns the result dict from /api/jarvis/mqtt."""
        api = _make_api()
        _mock_post_responses(api, [mqtt_config_response])

        result = await api.async_get_mqtt_config("test_device_id")

        assert result["msid"] == "test_msid_789"
        assert result["password"] == "test_mqtt_pass"

    @pytest.mark.asyncio
    async def test_caches_mqtt_config(self, mqtt_config_response: dict) -> None:
        """Second call returns cached result without hitting API."""
        api = _make_api()
        call_count = 0

        async def counting_post(path: str, data: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return mqtt_config_response

        api._post = counting_post  # type: ignore[method-assign]

        await api.async_get_mqtt_config("test_device_id")
        await api.async_get_mqtt_config("test_device_id")

        assert call_count == 1  # Only one API call


class TestInvalidateCache:
    """Test invalidate_cache method."""

    @pytest.mark.asyncio
    async def test_clears_both_caches(
        self, webrtc_config_response: dict, mqtt_config_response: dict
    ) -> None:
        """invalidate_cache clears both webrtc and mqtt caches."""
        api = _make_api()

        async def mock_post(path: str, data: dict) -> dict:
            if "config" in path:
                return webrtc_config_response
            return mqtt_config_response

        api._post = mock_post  # type: ignore[method-assign]

        # Populate caches
        await api.async_get_webrtc_config("test_device_id")
        await api.async_get_mqtt_config("test_device_id")

        assert api._webrtc_cache is not None
        assert api._mqtt_cache is not None

        # Invalidate
        api.invalidate_cache()

        assert api._webrtc_cache is None
        assert api._mqtt_cache is None
