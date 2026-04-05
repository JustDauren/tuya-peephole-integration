"""Async Tuya Smart App API client for the Tuya Peephole Camera integration.

Ports the synchronous prototype (auth_example.py) to fully async aiohttp,
replacing hand-rolled RSA with the cryptography library.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

from .const import API_TIMEOUT, EVENT_HISTORY_CACHE_TTL, MQTT_WEBRTC_CACHE_TTL
from .exceptions import TuyaApiError, TuyaAuthError

_LOGGER = logging.getLogger(__name__)


class TuyaSmartAPI:
    """Async Tuya Smart App API client.

    Handles authentication (RSA+MD5+PEM flow), WebRTC config retrieval,
    and MQTT credential retrieval for the Tuya Smart platform.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        email: str,
        password: str,
        country_code: str = "EU",
    ) -> None:
        """Initialize the API client.

        Args:
            session: aiohttp.ClientSession (from async_create_clientsession).
            host: Tuya Smart API host (e.g. protect-eu.ismartlife.me).
            email: User email for Tuya Smart App account.
            password: User password (encrypted before sending).
            country_code: Region code (e.g. EU, US, CN).
        """
        self._session = session
        self._host = host
        self._email = email
        self._password = password
        self._country_code = country_code

        # Public session state (populated after login)
        self.sid: str | None = None
        self.uid: str | None = None
        self.mqtt_url: str | None = None

        # Login lock to prevent concurrent login race conditions
        self._login_lock = asyncio.Lock()

        # Caches for WebRTC and MQTT config (5-minute TTL)
        self._webrtc_cache: dict[str, Any] | None = None
        self._webrtc_cache_time: float = 0
        self._mqtt_cache: dict[str, Any] | None = None
        self._mqtt_cache_time: float = 0

        # Message center cache (event history)
        self._message_cache: list[dict[str, Any]] | None = None
        self._message_cache_time: float = 0

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to Tuya Smart API and return parsed response.

        Args:
            path: API endpoint path (e.g. /api/login/token).
            data: Request body as dict.

        Returns:
            Parsed JSON response dict.

        Raises:
            TuyaAuthError: On authentication failures (USER_PASSWD_WRONG, USER_NOT_EXISTS).
            TuyaApiError: On network errors, timeouts, or non-auth API errors.
        """
        url = f"https://{self._host}{path}"
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)

        try:
            async with self._session.post(
                url,
                json=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "*/*",
                    "Origin": f"https://{self._host}",
                },
                timeout=timeout,
            ) as resp:
                result: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise TuyaApiError(f"API request failed: {err}") from err
        except TimeoutError as err:
            raise TuyaApiError(f"API request timed out: {path}") from err

        if not result.get("success"):
            error_code = result.get("errorCode", "unknown")
            error_msg = result.get("errorMsg", str(result))
            if error_code in ("USER_PASSWD_WRONG", "USER_NOT_EXISTS"):
                raise TuyaAuthError(f"Authentication failed: {error_msg}")
            raise TuyaApiError(f"API error {error_code}: {error_msg}")

        return result

    async def async_login(self) -> dict[str, Any]:
        """Perform full Tuya login: token -> RSA encrypt password -> login.

        Step 1: POST /api/login/token to get token + RSA public key (pbKey).
        Step 2: MD5(password) -> RSA PKCS1v15 encrypt -> hex.
        Step 3: POST /api/private/email/login to get sid, uid, mobileMqttsUrl.

        Returns:
            Login result dict containing sid, uid, domain info.

        Raises:
            TuyaAuthError: On wrong credentials.
            TuyaApiError: On network or API errors.
        """
        async with self._login_lock:
            # Step 1: Get token + RSA public key
            token_resp = await self._post(
                "/api/login/token",
                {
                    "countryCode": self._country_code,
                    "username": self._email,
                    "isUid": False,
                },
            )
            td = token_resp["result"]
            token = td["token"]
            pb_key = td.get("pbKey", td.get("publicKey"))

            # Step 2: RSA encrypt MD5(password) using cryptography library
            der_bytes = base64.b64decode(pb_key)
            public_key = load_der_public_key(der_bytes)
            passwd_md5 = hashlib.md5(self._password.encode()).hexdigest()
            encrypted = public_key.encrypt(passwd_md5.encode(), padding.PKCS1v15())
            encrypted_hex = encrypted.hex()

            # Step 3: Login with encrypted password
            login_resp = await self._post(
                "/api/private/email/login",
                {
                    "countryCode": self._country_code,
                    "email": self._email,
                    "passwd": encrypted_hex,
                    "token": token,
                    "ifencrypt": 1,
                    "options": '{"group":1}',
                },
            )

            result = login_resp["result"]
            self.sid = result["sid"]
            self.uid = result["uid"]
            self.mqtt_url = result["domain"]["mobileMqttsUrl"]

            _LOGGER.debug(
                "Tuya login successful for %s (uid=%s)", self._email, self.uid
            )
            return result

    async def async_get_device_list(self) -> list[dict[str, Any]]:
        """Get list of user's devices from Tuya Smart App API.

        Returns list of devices with id, name, localKey, category, etc.
        Used during config flow to let user pick their camera device.
        """
        resp = await self._post(
            "/api/discovery/pns/device/list",
            {"type": "all"},
        )
        devices: list[dict[str, Any]] = resp.get("result", [])
        return devices

    async def async_get_webrtc_config(self, device_id: str) -> dict[str, Any]:
        """Get WebRTC configuration for a device.

        Retrieves motoId, auth, skill, and supportsWebrtc from the Tuya API.
        Results are cached for MQTT_WEBRTC_CACHE_TTL seconds.

        Args:
            device_id: Tuya device ID.

        Returns:
            WebRTC config dict with motoId, auth, skill keys.
        """
        if (
            self._webrtc_cache is not None
            and (time.time() - self._webrtc_cache_time) < MQTT_WEBRTC_CACHE_TTL
        ):
            return self._webrtc_cache

        resp = await self._post("/api/jarvis/config", {"devId": device_id})
        self._webrtc_cache = resp["result"]
        self._webrtc_cache_time = time.time()
        return self._webrtc_cache

    async def async_get_mqtt_config(self, device_id: str) -> dict[str, Any]:
        """Get MQTT credentials for WebRTC signaling.

        Retrieves msid and password from the Tuya API.
        Results are cached for MQTT_WEBRTC_CACHE_TTL seconds.

        Args:
            device_id: Tuya device ID.

        Returns:
            MQTT config dict with msid and password keys.
        """
        if (
            self._mqtt_cache is not None
            and (time.time() - self._mqtt_cache_time) < MQTT_WEBRTC_CACHE_TTL
        ):
            return self._mqtt_cache

        resp = await self._post("/api/jarvis/mqtt", {"devId": device_id})
        self._mqtt_cache = resp["result"]
        self._mqtt_cache_time = time.time()
        return self._mqtt_cache

    async def async_get_snapshot(self, device_id: str) -> str | None:
        """Request snapshot URL from Tuya API.

        Args:
            device_id: Tuya device ID.

        Returns:
            URL string for the snapshot JPEG, or None if not available.
        """
        try:
            resp = await self._post(
                "/api/device/capture",
                {"devId": device_id},
            )
            return resp.get("result", {}).get("url")
        except Exception:
            _LOGGER.debug("Snapshot URL request failed", exc_info=True)
            return None

    async def async_get_message_list(
        self, device_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get event messages from Tuya Message Center.

        Retrieves recent doorbell/motion events for the device.
        Results are cached for EVENT_HISTORY_CACHE_TTL seconds.

        The Tuya Smart App API endpoint is /api/discovery/lite/msgcenter/msgList.
        Request body: {"msgSrcId": device_id, "limit": limit, "offset": 0}

        Args:
            device_id: Tuya device ID.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts, each containing: msgId, msgTypeCode,
            msgTitle, msgContent, time, icon, attachPic (thumbnail URL).
        """
        if (
            self._message_cache is not None
            and (time.time() - self._message_cache_time)
            < EVENT_HISTORY_CACHE_TTL
        ):
            return self._message_cache

        resp = await self._post(
            "/api/discovery/lite/msgcenter/msgList",
            {"msgSrcId": device_id, "limit": limit, "offset": 0},
        )
        result = resp.get("result", {})
        # Tuya returns {"datas": [...], "totalCount": N}
        events: list[dict[str, Any]] = result.get("datas", [])
        self._message_cache = events
        self._message_cache_time = time.time()
        return events

    def invalidate_cache(self) -> None:
        """Clear cached WebRTC and MQTT config.

        Used when re-fetching config for new streams.
        """
        self._webrtc_cache = None
        self._mqtt_cache = None
        self._message_cache = None
