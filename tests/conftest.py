"""Shared test fixtures for tuya_peephole tests."""

from __future__ import annotations

import asyncio
import base64
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

# ---------------------------------------------------------------------------
# Mock homeassistant module hierarchy before any integration imports.
# Required because homeassistant is not installed in the dev environment.
# ---------------------------------------------------------------------------

_ha = types.ModuleType("homeassistant")
_ha_exceptions = types.ModuleType("homeassistant.exceptions")


class _ConfigEntryAuthFailed(Exception):
    """Mock ConfigEntryAuthFailed for testing."""


class _ConfigEntryNotReady(Exception):
    """Mock ConfigEntryNotReady for testing."""


_ha_exceptions.ConfigEntryAuthFailed = _ConfigEntryAuthFailed  # type: ignore[attr-defined]
_ha_exceptions.ConfigEntryNotReady = _ConfigEntryNotReady  # type: ignore[attr-defined]

# homeassistant.helpers and sub-modules
_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_helpers_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
_ha_helpers_aiohttp.async_create_clientsession = MagicMock()  # type: ignore[attr-defined]

_ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
_ha_helpers_event.async_track_time_interval = MagicMock()  # type: ignore[attr-defined]
_ha_helpers_event.async_call_later = MagicMock()  # type: ignore[attr-defined]

# homeassistant.core
_ha_core = types.ModuleType("homeassistant.core")
_ha_core.HomeAssistant = MagicMock  # type: ignore[attr-defined]
_ha_core.CALLBACK_TYPE = None  # type: ignore[attr-defined]
_ha_core.callback = lambda f: f  # identity decorator  # type: ignore[attr-defined]

# homeassistant.const
_ha_const = types.ModuleType("homeassistant.const")


class _MockPlatform:
    """Mock Platform enum."""

    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CAMERA = "camera"
    SENSOR = "sensor"


_ha_const.Platform = _MockPlatform  # type: ignore[attr-defined]
_ha_const.PERCENTAGE = "%"  # type: ignore[attr-defined]
_ha_const.SIGNAL_STRENGTH_DECIBELS_MILLIWATT = "dBm"  # type: ignore[attr-defined]

# homeassistant.helpers.update_coordinator
_ha_helpers_update_coordinator = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)


class _MockDataUpdateCoordinator:
    """Minimal mock DataUpdateCoordinator for testing."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self._listeners = {}

    async def async_config_entry_first_refresh(self):
        await self._async_setup()
        self.data = await self._async_update_data()

    async def _async_setup(self):
        pass

    async def _async_update_data(self):
        return {}

    def async_set_updated_data(self, data):
        self.data = data

    def async_update_listeners(self):
        pass


class _MockCoordinatorEntity:
    """Minimal mock CoordinatorEntity for testing."""

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return True


_ha_helpers_update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator  # type: ignore[attr-defined]
_ha_helpers_update_coordinator.CoordinatorEntity = _MockCoordinatorEntity  # type: ignore[attr-defined]

# homeassistant.helpers.device_registry
_ha_helpers_device_registry = types.ModuleType(
    "homeassistant.helpers.device_registry"
)


class _MockDeviceInfo:
    """Mock DeviceInfo for testing."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


_ha_helpers_device_registry.DeviceInfo = _MockDeviceInfo  # type: ignore[attr-defined]

# homeassistant.components.binary_sensor
_ha_components = types.ModuleType("homeassistant.components")
_ha_binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")


class _MockBinarySensorDeviceClass:
    """Mock BinarySensorDeviceClass."""

    MOTION = "motion"
    OCCUPANCY = "occupancy"


class _MockBinarySensorEntity:
    """Mock BinarySensorEntity."""

    _attr_device_class = None
    _attr_is_on = None


_ha_binary_sensor.BinarySensorDeviceClass = _MockBinarySensorDeviceClass  # type: ignore[attr-defined]
_ha_binary_sensor.BinarySensorEntity = _MockBinarySensorEntity  # type: ignore[attr-defined]

# homeassistant.components.button
_ha_button = types.ModuleType("homeassistant.components.button")


class _MockButtonEntity:
    """Mock ButtonEntity."""

    _attr_icon = None


_ha_button.ButtonEntity = _MockButtonEntity  # type: ignore[attr-defined]

# homeassistant.components.sensor
_ha_sensor = types.ModuleType("homeassistant.components.sensor")


class _MockSensorDeviceClass:
    """Mock SensorDeviceClass."""

    BATTERY = "battery"
    SIGNAL_STRENGTH = "signal_strength"
    TEMPERATURE = "temperature"


class _MockSensorStateClass:
    """Mock SensorStateClass."""

    MEASUREMENT = "measurement"
    TOTAL = "total"


class _MockSensorEntity:
    """Mock SensorEntity."""

    _attr_device_class = None
    _attr_state_class = None
    _attr_native_unit_of_measurement = None
    _attr_native_value = None
    _attr_entity_registry_enabled_default = True


_ha_sensor.SensorDeviceClass = _MockSensorDeviceClass  # type: ignore[attr-defined]
_ha_sensor.SensorStateClass = _MockSensorStateClass  # type: ignore[attr-defined]
_ha_sensor.SensorEntity = _MockSensorEntity  # type: ignore[attr-defined]

# homeassistant.helpers.entity_platform
_ha_helpers_entity_platform = types.ModuleType(
    "homeassistant.helpers.entity_platform"
)
_ha_helpers_entity_platform.AddEntitiesCallback = None  # type: ignore[attr-defined]

# homeassistant.config_entries
_ha_config_entries = types.ModuleType("homeassistant.config_entries")


class _MockConfigFlow:
    """Minimal mock of HA ConfigFlow for testing."""

    hass = None
    flow_id = "test_flow"
    _progress: dict = {}

    def __init_subclass__(cls, *, domain: str = "", **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)

    async def async_set_unique_id(self, unique_id: str) -> None:
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        pass

    def async_create_entry(self, *, title: str, data: dict) -> dict:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self, *, step_id: str, data_schema: object = None, errors: dict | None = None
    ) -> dict:
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    def async_abort(self, *, reason: str) -> dict:
        return {"type": "abort", "reason": reason}


class _MockConfigEntry:
    """Minimal mock of HA ConfigEntry for testing."""

    def __init__(
        self,
        *,
        entry_id: str = "test_entry_id",
        domain: str = "tuya_peephole",
        title: str = "Test Entry",
        data: dict | None = None,
        options: dict | None = None,
        unique_id: str | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.domain = domain
        self.title = title
        self.data = data or {}
        self.options = options or {}
        self.unique_id = unique_id
        self._on_unload_callbacks: list = []

    def async_on_unload(self, func: object) -> None:
        self._on_unload_callbacks.append(func)

    def async_start_reauth(self, hass: object) -> None:
        pass

    def add_update_listener(self, listener: object) -> object:
        return listener


class _MockOptionsFlow:
    """Mock OptionsFlow."""

    def __init__(self, config_entry):
        self.config_entry = config_entry


class _MockOptionsFlowWithConfigEntry:
    """Mock OptionsFlowWithConfigEntry (HA 2025.1+)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.options = dict(config_entry.data) if hasattr(config_entry, 'data') else {}

    def async_create_entry(self, *, data=None, **kwargs):
        return {"type": "create_entry", "data": data or {}}

    def async_show_form(self, *, step_id="", data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    def add_suggested_values_to_schema(self, schema, values):
        return schema


_ha_config_entries.ConfigFlow = _MockConfigFlow  # type: ignore[attr-defined]
_ha_config_entries.ConfigEntry = _MockConfigEntry  # type: ignore[attr-defined]
_ha_config_entries.OptionsFlow = _MockOptionsFlow  # type: ignore[attr-defined]
_ha_config_entries.OptionsFlowWithConfigEntry = _MockOptionsFlowWithConfigEntry  # type: ignore[attr-defined]

# homeassistant.data_entry_flow
_ha_data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
_ha_data_entry_flow.FlowResult = dict  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Mock paho-mqtt module hierarchy before any integration imports.
# ---------------------------------------------------------------------------

_paho = types.ModuleType("paho")
_paho_mqtt = types.ModuleType("paho.mqtt")
_paho_mqtt_client = types.ModuleType("paho.mqtt.client")

# Constants
_paho_mqtt_client.MQTT_ERR_SUCCESS = 0  # type: ignore[attr-defined]
_paho_mqtt_client.MQTTv311 = 4  # type: ignore[attr-defined]


class _MockCallbackAPIVersion:
    """Mock CallbackAPIVersion."""

    VERSION2 = 2


_paho_mqtt_client.CallbackAPIVersion = _MockCallbackAPIVersion  # type: ignore[attr-defined]


class _MockConnectFlags:
    """Mock ConnectFlags."""

    pass


_paho_mqtt_client.ConnectFlags = _MockConnectFlags  # type: ignore[attr-defined]


class _MockDisconnectFlags:
    """Mock DisconnectFlags."""

    pass


_paho_mqtt_client.DisconnectFlags = _MockDisconnectFlags  # type: ignore[attr-defined]


class _MockReasonCode:
    """Mock ReasonCode."""

    def __init__(self, value=0):
        self.value = value

    def __eq__(self, other):
        if isinstance(other, int):
            return self.value == other
        if isinstance(other, _MockReasonCode):
            return self.value == other.value
        return NotImplemented

    def __repr__(self):
        return f"ReasonCode({self.value})"


_paho_mqtt_client.ReasonCode = _MockReasonCode  # type: ignore[attr-defined]


class _MockProperties:
    """Mock Properties."""

    pass


_paho_mqtt_client.Properties = _MockProperties  # type: ignore[attr-defined]


class _MockMQTTMessage:
    """Mock MQTTMessage."""

    def __init__(self, topic="", payload=b""):
        self.topic = topic
        self.payload = payload


_paho_mqtt_client.MQTTMessage = _MockMQTTMessage  # type: ignore[attr-defined]


class _MockPahoClient:
    """Mock paho.mqtt.client.Client with standard methods."""

    def __init__(self, callback_api_version=None, client_id=None, protocol=None):
        self._client_id = (client_id or "").encode() if isinstance(client_id, str) else b""
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.on_socket_open = None
        self.on_socket_close = None
        self.on_socket_register_write = None
        self.on_socket_unregister_write = None

    def username_pw_set(self, username, password=None):
        self._username = username
        self._password = password

    def tls_set_context(self, context=None):
        self._ssl_context = context

    def connect(self, host, port=1883, keepalive=60):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topic, qos=0):
        pass

    def publish(self, topic, payload=None, qos=0):
        pass

    def loop_read(self):
        return 0

    def loop_write(self):
        return 0

    def loop_misc(self):
        return 0

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self._reconnect_min_delay = min_delay
        self._reconnect_max_delay = max_delay


_paho_mqtt_client.Client = _MockPahoClient  # type: ignore[attr-defined]

sys.modules["paho"] = _paho
sys.modules["paho.mqtt"] = _paho_mqtt
sys.modules["paho.mqtt.client"] = _paho_mqtt_client

# ---------------------------------------------------------------------------
# Mock homeassistant.util.dt module (used by recorder.py for timestamps).
# ---------------------------------------------------------------------------

_ha_util = types.ModuleType("homeassistant.util")
_ha_util_dt = types.ModuleType("homeassistant.util.dt")

from datetime import datetime, timezone  # noqa: E402

_ha_util_dt.now = MagicMock(side_effect=lambda: datetime.now(tz=timezone.utc))  # type: ignore[attr-defined]
sys.modules["homeassistant.util"] = _ha_util
sys.modules["homeassistant.util.dt"] = _ha_util_dt

# ---------------------------------------------------------------------------
# Mock aiortc module hierarchy for Phase 5 recording tests.
# ---------------------------------------------------------------------------

_mock_aiortc = MagicMock()
_mock_aiortc_contrib = MagicMock()
_mock_aiortc_contrib_media = MagicMock()

# RTCPeerConnection mock
_mock_pc_class = MagicMock()
_mock_pc_instance = AsyncMock()
_mock_pc_instance.connectionState = "new"
_mock_pc_instance.addTransceiver = MagicMock()
_mock_pc_instance.createOffer = AsyncMock(
    return_value=MagicMock(sdp="v=0\r\nmock offer sdp", type="offer")
)
_mock_pc_instance.setLocalDescription = AsyncMock()
_mock_pc_instance.setRemoteDescription = AsyncMock()
_mock_pc_instance.close = AsyncMock()
_mock_pc_instance.on = MagicMock(side_effect=lambda event: lambda fn: fn)  # decorator
_mock_pc_class.return_value = _mock_pc_instance
_mock_aiortc.RTCPeerConnection = _mock_pc_class

# RTCSessionDescription, RTCConfiguration, RTCIceServer
_mock_aiortc.RTCSessionDescription = MagicMock()
_mock_aiortc.RTCConfiguration = MagicMock()
_mock_aiortc.RTCIceServer = MagicMock()

# MediaRecorder mock
_mock_recorder_class = MagicMock()
_mock_recorder_instance = MagicMock()
_mock_recorder_instance.addTrack = MagicMock()
_mock_recorder_instance.start = AsyncMock()
_mock_recorder_instance.stop = AsyncMock()
_mock_recorder_class.return_value = _mock_recorder_instance
_mock_aiortc_contrib_media.MediaRecorder = _mock_recorder_class

# Wire module hierarchy
_mock_aiortc.contrib = _mock_aiortc_contrib
_mock_aiortc.contrib.media = _mock_aiortc_contrib_media

sys.modules["aiortc"] = _mock_aiortc
sys.modules["aiortc.contrib"] = _mock_aiortc_contrib
sys.modules["aiortc.contrib.media"] = _mock_aiortc_contrib_media

# ---------------------------------------------------------------------------
# Mock HA media_source and media_player modules for Phase 5 media source tests.
# ---------------------------------------------------------------------------

_mock_ha_media_player = types.ModuleType("homeassistant.components.media_player")


class _MockMediaClass:
    """Mock MediaClass enum."""

    DIRECTORY = "directory"
    VIDEO = "video"


class _MockMediaType:
    """Mock MediaType enum."""

    VIDEO = "video/mp4"


_mock_ha_media_player.MediaClass = _MockMediaClass  # type: ignore[attr-defined]
_mock_ha_media_player.MediaType = _MockMediaType  # type: ignore[attr-defined]
sys.modules["homeassistant.components.media_player"] = _mock_ha_media_player

_mock_ha_media_source = types.ModuleType("homeassistant.components.media_source")


class _MockMediaSource:
    """Mock MediaSource base class."""

    def __init__(self, domain):
        self.domain = domain


class _MockMediaSourceItem:
    """Mock MediaSourceItem."""

    def __init__(self, identifier=None):
        self.identifier = identifier


class _MockPlayMedia:
    """Mock PlayMedia."""

    def __init__(self, url="", mime_type=""):
        self.url = url
        self.mime_type = mime_type


class _MockBrowseMediaSource:
    """Mock BrowseMediaSource."""

    def __init__(self, *, domain="", identifier="", media_class="",
                 media_content_type="", title="", can_play=False,
                 can_expand=False, children=None, thumbnail=None):
        self.domain = domain
        self.identifier = identifier
        self.media_class = media_class
        self.media_content_type = media_content_type
        self.title = title
        self.can_play = can_play
        self.can_expand = can_expand
        self.children = children or []
        self.thumbnail = thumbnail


_mock_ha_media_source.MediaSource = _MockMediaSource  # type: ignore[attr-defined]
_mock_ha_media_source.MediaSourceItem = _MockMediaSourceItem  # type: ignore[attr-defined]
_mock_ha_media_source.PlayMedia = _MockPlayMedia  # type: ignore[attr-defined]
_mock_ha_media_source.BrowseMediaSource = _MockBrowseMediaSource  # type: ignore[attr-defined]
sys.modules["homeassistant.components.media_source"] = _mock_ha_media_source

# Register all mock modules
sys.modules["homeassistant"] = _ha
sys.modules["homeassistant.exceptions"] = _ha_exceptions
sys.modules["homeassistant.core"] = _ha_core
sys.modules["homeassistant.const"] = _ha_const
sys.modules["homeassistant.helpers"] = _ha_helpers
sys.modules["homeassistant.helpers.aiohttp_client"] = _ha_helpers_aiohttp
sys.modules["homeassistant.helpers.event"] = _ha_helpers_event
sys.modules["homeassistant.helpers.update_coordinator"] = _ha_helpers_update_coordinator
sys.modules["homeassistant.helpers.device_registry"] = _ha_helpers_device_registry
sys.modules["homeassistant.helpers.entity_platform"] = _ha_helpers_entity_platform
sys.modules["homeassistant.components"] = _ha_components
sys.modules["homeassistant.components.binary_sensor"] = _ha_binary_sensor
sys.modules["homeassistant.components.button"] = _ha_button
sys.modules["homeassistant.components.sensor"] = _ha_sensor
sys.modules["homeassistant.config_entries"] = _ha_config_entries
sys.modules["homeassistant.data_entry_flow"] = _ha_data_entry_flow

# ---------------------------------------------------------------------------
# Mock webrtc_models module (HA-bundled) for Phase 3 WebRTC testing.
# ---------------------------------------------------------------------------

_mock_webrtc_models = types.ModuleType("webrtc_models")


class _MockRTCIceCandidateInit:
    """Mock RTCIceCandidateInit for testing."""

    def __init__(
        self,
        candidate="",
        sdp_mid=None,
        sdp_m_line_index=None,
        user_fragment=None,
    ):
        self.candidate = candidate
        self.sdp_mid = sdp_mid
        self.sdp_m_line_index = sdp_m_line_index
        self.user_fragment = user_fragment


class _MockRTCIceServer:
    """Mock RTCIceServer for testing."""

    def __init__(self, urls="", username=None, credential=None):
        self.urls = urls
        self.username = username
        self.credential = credential


class _MockRTCConfiguration:
    """Mock RTCConfiguration for testing."""

    def __init__(self, ice_servers=None):
        self.ice_servers = ice_servers or []


_mock_webrtc_models.RTCIceCandidateInit = _MockRTCIceCandidateInit  # type: ignore[attr-defined]
_mock_webrtc_models.RTCIceServer = _MockRTCIceServer  # type: ignore[attr-defined]
_mock_webrtc_models.RTCConfiguration = _MockRTCConfiguration  # type: ignore[attr-defined]
sys.modules["webrtc_models"] = _mock_webrtc_models

# ---------------------------------------------------------------------------
# Mock HA camera module hierarchy for Phase 3 camera entity testing.
# ---------------------------------------------------------------------------

_mock_ha_camera = types.ModuleType("homeassistant.components.camera")


class _MockCamera:
    """Mock Camera base class for testing."""

    _attr_supported_features = 0
    _attr_has_entity_name = False
    _attr_name = None

    def __init__(self):
        self.hass = None

    async def async_camera_image(self, width=None, height=None):
        return None


class _MockCameraEntityFeature:
    """Mock CameraEntityFeature for testing."""

    STREAM = 1


_mock_ha_camera.Camera = _MockCamera  # type: ignore[attr-defined]
_mock_ha_camera.CameraEntityFeature = _MockCameraEntityFeature()  # type: ignore[attr-defined]
sys.modules["homeassistant.components.camera"] = _mock_ha_camera

# HA camera webrtc sub-module mocks
_mock_ha_camera_webrtc = types.ModuleType("homeassistant.components.camera.webrtc")


class _MockWebRTCAnswer:
    """Mock WebRTCAnswer for testing."""

    def __init__(self, answer=""):
        self.answer = answer


class _MockWebRTCCandidate:
    """Mock WebRTCCandidate for testing."""

    def __init__(self, candidate=None):
        self.candidate = candidate


class _MockWebRTCClientConfiguration:
    """Mock WebRTCClientConfiguration for testing."""

    def __init__(self, configuration=None):
        self.configuration = configuration


class _MockWebRTCError:
    """Mock WebRTCError for testing."""

    def __init__(self, code="", message=""):
        self.code = code
        self.message = message


_mock_ha_camera_webrtc.WebRTCAnswer = _MockWebRTCAnswer  # type: ignore[attr-defined]
_mock_ha_camera_webrtc.WebRTCCandidate = _MockWebRTCCandidate  # type: ignore[attr-defined]
_mock_ha_camera_webrtc.WebRTCClientConfiguration = _MockWebRTCClientConfiguration  # type: ignore[attr-defined]
_mock_ha_camera_webrtc.WebRTCError = _MockWebRTCError  # type: ignore[attr-defined]
_mock_ha_camera_webrtc.WebRTCSendMessage = None  # type: ignore[attr-defined]
sys.modules["homeassistant.components.camera.webrtc"] = _mock_ha_camera_webrtc

# ---------------------------------------------------------------------------
# RSA test key: a 2048-bit RSA public key for testing only.
# Generated once for reproducibility -- not a real credential.
# DER-encoded SubjectPublicKeyInfo (base64)
# ---------------------------------------------------------------------------
TEST_RSA_PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA68NqTWKxt7iL0PwG"
    "KGO+TgE0QOx777dZ1gMCeqW9sIv1z5fdlfkb1yBkJLIe9HYQHhjTvVlVxZ0u"
    "2wDD2MtrLx07UQb3X3lQHyeGnioAgE5ftT9TjpB/ktNSwFYMN3y70SNWyfTh"
    "LEvO+0p+BKHAxmMfc9OIfzkzMvg4JjLOrTnOMbXmH/ei3+jbVo40EVWGC369"
    "x3jRTmb4JaphpkmoZWa6XwFWDWRTRKQKZ+zM6Q9DHjULkBFxbU8lgL/ShzK4"
    "mQ4CQMskuIEebShuE4nobN6j97PgdXUE5ifenlIKDvGgee0f1QvoXI57y5+QU"
    "eymJByUVHDf3sR4ftcTC1HwCQIDAQAB"
)


# ---------------------------------------------------------------------------
# Fixtures: API response mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    """Create a mock aiohttp.ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def aiohttp_client_session():
    """Create a real aiohttp.ClientSession for mocking."""
    return None


@pytest.fixture
def test_rsa_pubkey_b64() -> str:
    """Return the test RSA public key in base64."""
    return TEST_RSA_PUBLIC_KEY_B64


@pytest.fixture
def token_response(test_rsa_pubkey_b64: str) -> dict:
    """Successful /api/login/token response."""
    return {
        "success": True,
        "result": {
            "token": "test_token_123",
            "pbKey": test_rsa_pubkey_b64,
        },
    }


@pytest.fixture
def login_response() -> dict:
    """Successful /api/private/email/login response."""
    return {
        "success": True,
        "result": {
            "sid": "test_sid_abc",
            "uid": "test_uid_def",
            "nickname": "TestUser",
            "domain": {
                "mobileMqttsUrl": "m1-eu.iot334.com",
            },
        },
    }


@pytest.fixture
def webrtc_config_response() -> dict:
    """Successful /api/jarvis/config response."""
    return {
        "success": True,
        "result": {
            "motoId": "test_moto_123",
            "auth": "test_auth_token",
            "skill": "webRTC",
            "supportsWebrtc": True,
        },
    }


@pytest.fixture
def mqtt_config_response() -> dict:
    """Successful /api/jarvis/mqtt response."""
    return {
        "success": True,
        "result": {
            "msid": "test_msid_789",
            "password": "test_mqtt_pass",
        },
    }


@pytest.fixture
def auth_error_response() -> dict:
    """Authentication error response from Tuya."""
    return {
        "success": False,
        "errorCode": "USER_PASSWD_WRONG",
        "errorMsg": "Password is incorrect",
    }


@pytest.fixture
def api_error_response() -> dict:
    """Generic API error response from Tuya."""
    return {
        "success": False,
        "errorCode": "SYSTEM_ERROR",
        "errorMsg": "Internal server error",
    }


@pytest.fixture
def mock_tuya_responses(
    token_response: dict,
    login_response: dict,
    webrtc_config_response: dict,
    mqtt_config_response: dict,
    auth_error_response: dict,
    api_error_response: dict,
) -> dict:
    """Canned Tuya API responses for testing (combined dict)."""
    return {
        "token": token_response,
        "login": login_response,
        "webrtc_config": webrtc_config_response,
        "mqtt_config": mqtt_config_response,
        "auth_error": auth_error_response,
        "api_error": api_error_response,
    }


# ---------------------------------------------------------------------------
# Fixtures: API client
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(mock_session: MagicMock):
    """Create TuyaSmartAPI with mock session for testing."""
    from custom_components.tuya_peephole.api import TuyaSmartAPI

    return TuyaSmartAPI(
        session=mock_session,
        host="protect-eu.ismartlife.me",
        email="test@example.com",
        password="testpass",
        country_code="EU",
    )


# ---------------------------------------------------------------------------
# Fixtures: Config entry data
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config_entry_data() -> dict:
    """Config entry data for testing."""
    from custom_components.tuya_peephole.const import (
        CONF_DEVICE_ID,
        CONF_EMAIL,
        CONF_LOCAL_KEY,
        CONF_PASSWORD,
        CONF_REGION,
    )

    return {
        CONF_EMAIL: "test@example.com",
        CONF_PASSWORD: "testpass",
        CONF_DEVICE_ID: "test_device_id_abc123",
        CONF_REGION: "eu",
        CONF_LOCAL_KEY: "testkey123",
    }


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a minimal mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    # Phase 2: config_entries methods used in __init__.py must be async
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_config_entry(mock_config_entry_data: dict) -> _MockConfigEntry:
    """Create a mock ConfigEntry with test data."""
    return _MockConfigEntry(
        entry_id="test_entry_id",
        domain="tuya_peephole",
        title="Tuya Peephole test_device_id_abc123",
        data=mock_config_entry_data,
        unique_id="test_device_id_abc123",
    )


# ---------------------------------------------------------------------------
# Phase 2 fixtures: MQTT client, coordinator, and message mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mqtt_client():
    """Create a mock TuyaMQTTClient for testing."""
    client = MagicMock()
    client.async_connect = AsyncMock()
    client.subscribe = MagicMock()
    client.publish = MagicMock()
    client.async_disconnect = AsyncMock()
    client.is_connected = True
    client.set_message_callback = MagicMock()
    client.set_on_connected_callback = MagicMock()
    client.set_on_disconnected_callback = MagicMock()
    return client


@pytest.fixture
def mock_hass_with_loop():
    """Create a mock hass with event loop for MQTT async testing."""
    hass = MagicMock()
    hass.data = {}
    hass.loop = asyncio.get_event_loop()
    hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    return hass


@pytest.fixture
def mock_coordinator(mock_hass_with_loop, mock_mqtt_client):
    """Create a mock TuyaPeepholeCoordinator with MQTT client for testing."""
    from custom_components.tuya_peephole.models import CameraState

    coordinator = MagicMock()
    coordinator.hass = mock_hass_with_loop
    coordinator.device_id = "test_device_id_abc123"
    coordinator.local_key = "testkey123"
    coordinator.mqtt_client = mock_mqtt_client
    coordinator.api = MagicMock()
    coordinator.data = {
        "camera_state": CameraState.SLEEPING,
        "motion_detected": False,
        "battery_percentage": None,
        "signal_strength": None,
        "last_events": [],
    }
    coordinator.camera_state = CameraState.SLEEPING
    coordinator.async_wake_camera = AsyncMock(return_value=True)
    coordinator.async_fetch_events = AsyncMock(return_value=[])
    coordinator.async_teardown = AsyncMock()
    return coordinator


@pytest.fixture
def sample_mqtt_messages():
    """Sample MQTT payloads for testing message parsing."""
    return {
        "wireless_awake": b'{"data":{"wireless_awake":true}}',
        "motion": b'{"data":{"pir":"1"}}',
        "binary_unknown": b"\x00\x01\x02\x03",
        "empty_json": b"{}",
    }


# ---------------------------------------------------------------------------
# Phase 3 fixtures: WebRTC signaling and camera entity test data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_sdp_offer():
    """Sample SDP offer with extmap lines for testing."""
    return (
        "v=0\r\n"
        "o=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "a=group:BUNDLE 0 1\r\n"
        "a=extmap-allow-mixed\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=extmap:1 urn:ietf:params:rtp-hdrext:ssrc-audio-level\r\n"
        "a=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\n"
        "a=rtpmap:111 opus/48000/2\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=extmap:3 urn:ietf:params:rtp-hdrext:toffset\r\n"
        "a=extmap:4 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\n"
        "a=rtpmap:96 H264/90000\r\n"
    )


@pytest.fixture
def sample_webrtc_config():
    """Sample WebRTC config from api.async_get_webrtc_config."""
    return {
        "motoId": "moto_cnpre002",
        "auth": "U+qtvRP+testauth",
        "skill": {"webRTC": "1"},
        "p2pConfig": {
            "ices": [
                {"urls": "stun:172.81.239.63:3478"},
                {
                    "urls": "turn:172.81.239.63:3478",
                    "username": "testuser",
                    "credential": "testcred",
                    "ttl": 3600,
                },
            ]
        },
    }


@pytest.fixture
def sample_mqtt_config():
    """Sample MQTT config from api.async_get_mqtt_config."""
    return {
        "msid": "abc123def456",
        "password": "mqttpassword",
    }


# ---------------------------------------------------------------------------
# Phase 4 fixtures: Reauth config entry
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config_entry_for_reauth(mock_config_entry_data):
    """Config entry with async_get_entry support for reauth testing."""
    entry = _MockConfigEntry(
        entry_id="test_entry_id",
        domain="tuya_peephole",
        title="Tuya Peephole test_device_id_abc123",
        data=mock_config_entry_data,
        unique_id="test_device_id_abc123",
    )
    return entry


# ---------------------------------------------------------------------------
# Phase 5 fixtures: Recording manager, aiortc mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_recording_coordinator(mock_coordinator):
    """Coordinator fixture extended for recording tests."""
    from custom_components.tuya_peephole.models import CameraState

    coord = mock_coordinator
    coord._on_motion_callbacks = []
    coord._charging_detected = False
    coord._battery_100_since = None
    coord.is_charging = False
    coord.camera_state = CameraState.AWAKE
    coord.register_motion_callback = MagicMock(
        side_effect=lambda cb: (
            coord._on_motion_callbacks.append(cb)
            or (lambda: coord._on_motion_callbacks.remove(cb))
        )
    )
    # API mocks for WebRTC/MQTT config
    coord.api.async_get_webrtc_config = AsyncMock(return_value={
        "motoId": "test_moto_123",
        "auth": "test_auth_token",
        "p2pConfig": {
            "ices": [
                {"urls": "stun:172.81.239.63:3478"},
            ]
        },
    })
    coord.api.async_get_mqtt_config = AsyncMock(return_value={
        "msid": "test_msid_789",
        "password": "test_mqtt_pass",
    })
    return coord
