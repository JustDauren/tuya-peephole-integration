"""Tests for TuyaPeepholeCamera entity (WebRTC SDP proxy lifecycle).

Tests entity properties, MQTT-aware availability, snapshot placeholder,
WebRTC client configuration, session rejection, close session cleanup,
ICE candidate forwarding, and signaling message handling.

Requirements covered: STRM-01, STRM-04, REL-04
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: create a mock coordinator specifically for camera tests
# ---------------------------------------------------------------------------


def _make_mock_coordinator(
    device_id="test_device_123",
    msid="abc123def456",
    moto_id="moto_cnpre002",
    auth="U+qtvRP+testauth",
    p2p_ices=None,
    camera_state=None,
    mqtt_connected=True,
):
    """Create a mock coordinator for camera entity tests.

    Args:
        device_id: Device ID for topic routing.
        msid: MQTT session ID.
        moto_id: Moto ID from jarvis/config.
        auth: Auth token for WebRTC offer.
        p2p_ices: ICE server list (default: STUN + TURN).
        camera_state: Camera state (default: AWAKE).
        mqtt_connected: Whether MQTT client reports connected.

    Returns:
        MagicMock coordinator with all expected attributes.
    """
    from custom_components.tuya_peephole.models import CameraState

    if camera_state is None:
        camera_state = CameraState.AWAKE
    if p2p_ices is None:
        p2p_ices = [
            {"urls": "stun:172.81.239.63:3478"},
            {
                "urls": "turn:172.81.239.63:3478",
                "username": "testuser",
                "credential": "testcred",
            },
        ]

    coordinator = MagicMock()
    coordinator.device_id = device_id
    coordinator.camera_state = camera_state
    coordinator.async_wake_camera = AsyncMock(return_value=True)

    # Mock MQTT client
    mqtt_client = MagicMock()
    mqtt_client.is_connected = mqtt_connected
    mqtt_client.subscribe = MagicMock()
    mqtt_client.publish = MagicMock()
    mqtt_client._client = MagicMock()
    mqtt_client._client.message_callback_add = MagicMock()
    mqtt_client._client.message_callback_remove = MagicMock()
    mqtt_client._client.unsubscribe = MagicMock()
    coordinator.mqtt_client = mqtt_client

    # Mock API
    api = AsyncMock()
    api.async_get_webrtc_config = AsyncMock(
        return_value={
            "motoId": moto_id,
            "auth": auth,
            "p2pConfig": {"ices": p2p_ices},
        }
    )
    api.async_get_mqtt_config = AsyncMock(
        return_value={
            "msid": msid,
            "password": "testpw",
        }
    )
    coordinator.api = api

    return coordinator


def _make_camera(coordinator=None):
    """Create a TuyaPeepholeCamera instance with the given coordinator."""
    from custom_components.tuya_peephole.camera import TuyaPeepholeCamera

    if coordinator is None:
        coordinator = _make_mock_coordinator()
    return TuyaPeepholeCamera(coordinator)


# ---------------------------------------------------------------------------
# Entity properties tests
# ---------------------------------------------------------------------------


class TestCameraEntityProperties:
    """Tests for TuyaPeepholeCamera entity attributes."""

    def test_entity_unique_id(self) -> None:
        """unique_id is {device_id}_camera."""
        camera = _make_camera()
        assert camera._attr_unique_id == "test_device_123_camera"

    def test_entity_supported_features(self) -> None:
        """CameraEntityFeature.STREAM is set."""
        from homeassistant.components.camera import CameraEntityFeature

        camera = _make_camera()
        assert camera._attr_supported_features == CameraEntityFeature.STREAM

    def test_entity_has_entity_name(self) -> None:
        """_attr_has_entity_name is True."""
        camera = _make_camera()
        assert camera._attr_has_entity_name is True

    def test_entity_name(self) -> None:
        """_attr_name is 'Camera'."""
        camera = _make_camera()
        assert camera._attr_name == "Camera"

    def test_entity_device_info(self) -> None:
        """Device identifiers contain (DOMAIN, device_id)."""
        from custom_components.tuya_peephole.const import DOMAIN

        camera = _make_camera()
        info = camera._attr_device_info
        assert (DOMAIN, "test_device_123") in info.identifiers


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------


class TestCameraAvailability:
    """Tests for MQTT-aware camera availability."""

    def test_available_when_mqtt_connected(self) -> None:
        """available is True when mqtt_client.is_connected is True."""
        coordinator = _make_mock_coordinator(mqtt_connected=True)
        camera = _make_camera(coordinator)
        assert camera.available is True

    def test_unavailable_when_mqtt_disconnected(self) -> None:
        """available is False when mqtt_client.is_connected is False."""
        coordinator = _make_mock_coordinator(mqtt_connected=False)
        camera = _make_camera(coordinator)
        assert camera.available is False

    def test_unavailable_when_no_mqtt_client(self) -> None:
        """available is False when mqtt_client is None."""
        coordinator = _make_mock_coordinator()
        coordinator.mqtt_client = None
        camera = _make_camera(coordinator)
        assert camera.available is False


# ---------------------------------------------------------------------------
# Snapshot placeholder test (STRM-04)
# ---------------------------------------------------------------------------


class TestCameraSnapshot:
    """Tests for async_camera_image placeholder."""

    @pytest.mark.asyncio
    async def test_async_camera_image_returns_none(self) -> None:
        """async_camera_image returns None (SDP proxy has no server-side media)."""
        camera = _make_camera()
        result = await camera.async_camera_image()
        assert result is None

    @pytest.mark.asyncio
    async def test_async_camera_image_with_dimensions_returns_none(self) -> None:
        """async_camera_image returns None even with width/height specified."""
        camera = _make_camera()
        result = await camera.async_camera_image(width=640, height=480)
        assert result is None


# ---------------------------------------------------------------------------
# WebRTC client configuration tests
# ---------------------------------------------------------------------------


class TestWebRTCClientConfiguration:
    """Tests for async_get_webrtc_client_configuration."""

    def test_webrtc_client_config_with_ices(self) -> None:
        """After _p2p_ices is populated, returns config with ICE servers."""
        camera = _make_camera()
        # Simulate populated _p2p_ices (normally set by _async_ensure_config)
        camera._p2p_ices = [
            {"urls": "stun:172.81.239.63:3478"},
            {
                "urls": "turn:172.81.239.63:3478",
                "username": "u",
                "credential": "c",
            },
        ]

        config = camera.async_get_webrtc_client_configuration()
        assert config.configuration is not None
        assert len(config.configuration.ice_servers) == 2
        assert config.configuration.ice_servers[0].urls == "stun:172.81.239.63:3478"
        assert config.configuration.ice_servers[1].urls == "turn:172.81.239.63:3478"
        assert config.configuration.ice_servers[1].username == "u"
        assert config.configuration.ice_servers[1].credential == "c"

    def test_webrtc_client_config_no_ices(self) -> None:
        """When _p2p_ices is None, returns config with empty ice_servers."""
        camera = _make_camera()
        camera._p2p_ices = None

        config = camera.async_get_webrtc_client_configuration()
        assert config.configuration is not None
        assert len(config.configuration.ice_servers) == 0

    def test_webrtc_client_config_empty_ices(self) -> None:
        """When _p2p_ices is empty list, returns config with empty ice_servers."""
        camera = _make_camera()
        camera._p2p_ices = []

        config = camera.async_get_webrtc_client_configuration()
        assert config.configuration is not None
        assert len(config.configuration.ice_servers) == 0


# ---------------------------------------------------------------------------
# Session rejection tests
# ---------------------------------------------------------------------------


class TestSessionRejection:
    """Tests for rejecting concurrent WebRTC sessions."""

    @pytest.mark.asyncio
    async def test_reject_second_session(self) -> None:
        """When _session_id is set, second offer sends WebRTCError."""
        camera = _make_camera()
        camera._session_id = "existing_session"
        camera.hass = MagicMock()

        send_message = MagicMock()
        await camera.async_handle_async_webrtc_offer(
            offer_sdp="v=0\r\n",
            session_id="new_session",
            send_message=send_message,
        )

        # send_message should be called with a WebRTCError
        send_message.assert_called_once()
        error = send_message.call_args[0][0]
        assert error.code == "webrtc_offer_failed"
        assert "Another WebRTC session is active" in error.message


# ---------------------------------------------------------------------------
# Close session tests
# ---------------------------------------------------------------------------


class TestCloseSession:
    """Tests for close_webrtc_session cleanup."""

    def _make_camera_with_active_session(self):
        """Create a camera with an active signaling session."""
        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)
        camera._session_id = "test_session_abc"
        camera._signaling_id = "sig123"
        camera._uid = "abc123def456"
        camera._moto_id = "moto_cnpre002"
        camera._send_message = MagicMock()
        # Mock signaling task as done (to avoid cancel issues)
        camera._signaling_task = MagicMock()
        camera._signaling_task.done.return_value = True
        return camera, coordinator

    def test_close_session_sends_disconnect(self) -> None:
        """close_webrtc_session publishes disconnect message to MQTT."""
        camera, coordinator = self._make_camera_with_active_session()

        camera.close_webrtc_session("test_session_abc")

        mqtt_client = coordinator.mqtt_client
        mqtt_client.publish.assert_called_once()
        # Verify the publish was a disconnect message
        call_args = mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload_bytes = call_args[0][1]
        assert "/av/moto/moto_cnpre002/" in topic
        msg = json.loads(payload_bytes)
        assert msg["data"]["header"]["type"] == "disconnect"

    def test_close_session_unsubscribes(self) -> None:
        """close_webrtc_session calls message_callback_remove and unsubscribe."""
        camera, coordinator = self._make_camera_with_active_session()

        camera.close_webrtc_session("test_session_abc")

        paho_client = coordinator.mqtt_client._client
        paho_client.message_callback_remove.assert_called_once()
        paho_client.unsubscribe.assert_called_once()

    def test_close_session_resets_state(self) -> None:
        """After close, session state is cleared."""
        camera, _coord = self._make_camera_with_active_session()

        camera.close_webrtc_session("test_session_abc")

        assert camera._session_id is None
        assert camera._send_message is None
        assert camera._signaling_id is None
        assert camera._signaling_task is None

    def test_close_wrong_session_noop(self) -> None:
        """close_webrtc_session with wrong session_id does nothing."""
        camera, coordinator = self._make_camera_with_active_session()

        camera.close_webrtc_session("wrong_session_xyz")

        # Nothing should be published or changed
        coordinator.mqtt_client.publish.assert_not_called()
        assert camera._session_id == "test_session_abc"
        assert camera._signaling_id == "sig123"


# ---------------------------------------------------------------------------
# ICE candidate forwarding tests
# ---------------------------------------------------------------------------


class TestICECandidateForwarding:
    """Tests for async_on_webrtc_candidate forwarding."""

    @pytest.mark.asyncio
    async def test_on_webrtc_candidate_publishes(self) -> None:
        """async_on_webrtc_candidate publishes formatted candidate to MQTT."""
        from webrtc_models import RTCIceCandidateInit

        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)
        camera._session_id = "sess_abc"
        camera._signaling_id = "sig456"
        camera._uid = "abc123def456"
        camera._moto_id = "moto_cnpre002"

        candidate = RTCIceCandidateInit(
            candidate="candidate:1 1 udp 2113937151 192.168.1.1 5000 typ host"
        )

        await camera.async_on_webrtc_candidate("sess_abc", candidate)

        mqtt_client = coordinator.mqtt_client
        mqtt_client.publish.assert_called_once()
        # Verify the published message contains the formatted candidate
        call_args = mqtt_client.publish.call_args
        payload_bytes = call_args[0][1]
        msg = json.loads(payload_bytes)
        assert msg["data"]["header"]["type"] == "candidate"
        # format_candidate_for_camera prepends "a=" prefix
        assert msg["data"]["msg"]["candidate"].startswith("a=candidate:")

    @pytest.mark.asyncio
    async def test_on_webrtc_candidate_wrong_session(self) -> None:
        """Candidate for non-matching session is ignored."""
        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)
        camera._session_id = "sess_abc"

        from webrtc_models import RTCIceCandidateInit

        candidate = RTCIceCandidateInit(candidate="candidate:1 1 udp")

        await camera.async_on_webrtc_candidate("wrong_session", candidate)

        coordinator.mqtt_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_webrtc_candidate_no_config(self) -> None:
        """Candidate is ignored if config (uid/moto_id) not loaded."""
        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)
        camera._session_id = "sess_abc"
        camera._uid = None
        camera._moto_id = None

        from webrtc_models import RTCIceCandidateInit

        candidate = RTCIceCandidateInit(candidate="candidate:1 1 udp")

        await camera.async_on_webrtc_candidate("sess_abc", candidate)

        coordinator.mqtt_client.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Signaling message handling tests
# ---------------------------------------------------------------------------


class TestSignalingMessageHandling:
    """Tests for _on_signaling_message callback."""

    def _make_signaling_message(
        self,
        msg_type="answer",
        signaling_id="sig123",
        msg_payload=None,
    ) -> bytes:
        """Build a protocol 302 signaling message for testing."""
        if msg_payload is None:
            if msg_type == "answer":
                msg_payload = {"sdp": "v=0\r\nanswer_sdp_from_camera"}
            elif msg_type == "candidate":
                msg_payload = {
                    "candidate": "a=candidate:1 1 udp 2113937151 10.0.0.1 5000 typ host\r\n"
                }
            else:
                msg_payload = {}

        message = {
            "protocol": 302,
            "pv": "2.2",
            "t": 1700000000,
            "data": {
                "header": {
                    "type": msg_type,
                    "from": "device_xyz",
                    "to": "uid_abc",
                    "sessionid": signaling_id,
                    "moto_id": "moto_test",
                },
                "msg": msg_payload,
            },
        }
        return json.dumps(message, separators=(",", ":")).encode("utf-8")

    def test_on_signaling_answer(self) -> None:
        """_on_signaling_message with answer type calls send_message(WebRTCAnswer)."""
        camera = _make_camera()
        send_message = MagicMock()
        camera._send_message = send_message

        payload = self._make_signaling_message("answer", "sig123")
        camera._on_signaling_message(payload, "sig123")

        send_message.assert_called_once()
        answer = send_message.call_args[0][0]
        assert answer.answer == "v=0\r\nanswer_sdp_from_camera"

    def test_on_signaling_answer_sets_event(self) -> None:
        """_on_signaling_message with answer type sets _answer_event."""
        camera = _make_camera()
        camera._send_message = MagicMock()

        assert not camera._answer_event.is_set()

        payload = self._make_signaling_message("answer", "sig123")
        camera._on_signaling_message(payload, "sig123")

        assert camera._answer_event.is_set()

    def test_on_signaling_candidate(self) -> None:
        """_on_signaling_message with candidate calls send_message(WebRTCCandidate)."""
        camera = _make_camera()
        send_message = MagicMock()
        camera._send_message = send_message

        payload = self._make_signaling_message("candidate", "sig123")
        camera._on_signaling_message(payload, "sig123")

        send_message.assert_called_once()
        candidate_msg = send_message.call_args[0][0]
        # WebRTCCandidate wraps RTCIceCandidateInit
        # clean_candidate_from_camera strips "a=" prefix and "\r\n" suffix
        assert candidate_msg.candidate.candidate == (
            "candidate:1 1 udp 2113937151 10.0.0.1 5000 typ host"
        )

    def test_on_signaling_wrong_session(self) -> None:
        """Message with wrong session ID is ignored (parse returns None)."""
        camera = _make_camera()
        send_message = MagicMock()
        camera._send_message = send_message

        payload = self._make_signaling_message("answer", "other_session")
        camera._on_signaling_message(payload, "my_session")

        send_message.assert_not_called()

    def test_on_signaling_no_send_message(self) -> None:
        """Answer message is ignored if _send_message is None."""
        camera = _make_camera()
        camera._send_message = None

        payload = self._make_signaling_message("answer", "sig123")
        # Should not raise
        camera._on_signaling_message(payload, "sig123")


# ---------------------------------------------------------------------------
# Config caching tests
# ---------------------------------------------------------------------------


class TestConfigCaching:
    """Tests for _async_ensure_config caching behavior."""

    @pytest.mark.asyncio
    async def test_ensure_config_fetches_once(self) -> None:
        """_async_ensure_config calls API only once (caches result)."""
        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)

        await camera._async_ensure_config()
        await camera._async_ensure_config()  # second call should use cache

        coordinator.api.async_get_webrtc_config.assert_called_once()
        coordinator.api.async_get_mqtt_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_config_populates_fields(self) -> None:
        """_async_ensure_config populates _uid, _moto_id, _auth, _p2p_ices."""
        coordinator = _make_mock_coordinator()
        camera = _make_camera(coordinator)

        await camera._async_ensure_config()

        assert camera._uid == "abc123def456"
        assert camera._moto_id == "moto_cnpre002"
        assert camera._auth == "U+qtvRP+testauth"
        assert len(camera._p2p_ices) == 2
