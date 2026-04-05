"""Camera entity for the Tuya Peephole Camera integration.

Provides live WebRTC video streaming via SDP proxy pattern:
the HA backend relays SDP offers/answers and ICE candidates
between the browser and camera through MQTT (protocol 302),
while the browser establishes a direct WebRTC connection to
the camera's TURN relay servers. No media flows through HA.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.webrtc import (
    WebRTCAnswer,
    WebRTCCandidate,
    WebRTCClientConfiguration,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from webrtc_models import RTCConfiguration, RTCIceCandidateInit, RTCIceServer

from .const import (
    DOMAIN,
    WEBRTC_PUBLISH_TOPIC_TEMPLATE,
    WEBRTC_SESSION_TIMEOUT,
    WEBRTC_STREAM_TYPE_HD,
    WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE,
)
from .models import CameraState
from .webrtc_signaling import (
    build_candidate_payload,
    build_disconnect_payload,
    build_offer_payload,
    build_protocol_302_message,
    clean_candidate_from_camera,
    format_candidate_for_camera,
    generate_session_id,
    parse_protocol_302_message,
    strip_sdp_extmap,
)

if TYPE_CHECKING:
    from .coordinator import TuyaPeepholeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya Peephole camera entity."""
    coordinator: TuyaPeepholeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TuyaPeepholeCamera(coordinator)])


class TuyaPeepholeCamera(Camera):
    """Tuya Peephole camera with WebRTC SDP proxy via MQTT protocol 302.

    Extends Camera directly (not CoordinatorEntity) because the camera entity
    has its own lifecycle methods (async_handle_async_webrtc_offer,
    close_webrtc_session) that do not align with CoordinatorEntity's update
    pattern. Uses the coordinator for wake and MQTT access but manages its
    own WebRTC session state.
    """

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_has_entity_name = True
    _attr_name = "Camera"

    def __init__(self, coordinator: TuyaPeepholeCoordinator) -> None:
        """Initialize the camera entity.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
        """
        super().__init__()
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=f"Tuya Peephole {coordinator.device_id[-6:]}",
            manufacturer="Tuya",
            model="Peephole Camera",
        )

        # WebRTC session state
        self._session_id: str | None = None
        self._signaling_id: str | None = None
        self._send_message: WebRTCSendMessage | None = None
        self._answer_event: asyncio.Event = asyncio.Event()
        self._signaling_task: asyncio.Task[None] | None = None

        # Cached config (populated on first offer)
        self._webrtc_config: dict[str, Any] | None = None
        self._mqtt_config: dict[str, Any] | None = None
        self._uid: str | None = None
        self._moto_id: str | None = None
        self._auth: str | None = None
        self._p2p_ices: list[dict[str, Any]] | None = None

    @property
    def available(self) -> bool:
        """Return True if MQTT is connected (camera can be woken)."""
        return (
            self.coordinator.mqtt_client is not None
            and self.coordinator.mqtt_client.is_connected
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Capture snapshot from camera.

        Attempts to fetch a snapshot by:
        1. Wake camera if sleeping
        2. Request snapshot URL from Tuya API
        3. Download JPEG from the URL

        Falls back to latest event thumbnail if direct snapshot fails.
        """
        # Step 1: Wake camera if sleeping
        if self.coordinator.camera_state != CameraState.AWAKE:
            awake = await self.coordinator.async_wake_camera()
            if not awake:
                _LOGGER.warning("Cannot snapshot: camera did not wake")
                return await self._fetch_event_thumbnail()

        # Step 2: Try Tuya snapshot API
        try:
            snapshot_url = await self.coordinator.api.async_get_snapshot(
                self.coordinator.device_id
            )
            if snapshot_url:
                return await self._download_image(snapshot_url)
        except Exception:
            _LOGGER.debug(
                "Snapshot API failed, trying event thumbnail",
                exc_info=True,
            )

        # Step 3: Fallback to latest event thumbnail
        return await self._fetch_event_thumbnail()

    async def _fetch_event_thumbnail(self) -> bytes | None:
        """Fetch the most recent event thumbnail as fallback snapshot."""
        try:
            events = await self.coordinator.api.async_get_message_list(
                self.coordinator.device_id, limit=1
            )
            if events and events[0].get("attachPic"):
                return await self._download_image(events[0]["attachPic"])
        except Exception:
            _LOGGER.debug("Event thumbnail fetch failed", exc_info=True)
        return None

    async def _download_image(self, url: str) -> bytes | None:
        """Download image from URL using the API session."""
        try:
            async with self.coordinator.api._session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception:
            _LOGGER.debug("Image download failed: %s", url, exc_info=True)
        return None

    async def _async_ensure_config(self) -> None:
        """Fetch and cache WebRTC and MQTT config from Tuya API."""
        if self._webrtc_config is None:
            self._webrtc_config = (
                await self.coordinator.api.async_get_webrtc_config(
                    self.coordinator.device_id
                )
            )
            self._moto_id = self._webrtc_config["motoId"]
            self._auth = self._webrtc_config["auth"]
            self._p2p_ices = (
                self._webrtc_config.get("p2pConfig", {}).get("ices", [])
            )

        if self._mqtt_config is None:
            self._mqtt_config = (
                await self.coordinator.api.async_get_mqtt_config(
                    self.coordinator.device_id
                )
            )
            self._uid = self._mqtt_config["msid"]

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Relay SDP offer to camera via MQTT, return answer via send_message callback.

        Flow:
        1. Wake camera if sleeping (fire-and-forget, do not wait for full confirmation)
        2. Fetch WebRTC/MQTT config from API
        3. Subscribe to answer topic on MQTT
        4. Strip extmap from SDP, publish offer via protocol 302
        5. Wait for answer from camera, forward to browser via send_message
        6. Forward camera ICE candidates to browser via send_message
        """
        # Reject if another session is active (single session at a time)
        if self._session_id is not None:
            send_message(
                WebRTCError(
                    "webrtc_offer_failed",
                    "Another WebRTC session is active",
                )
            )
            return

        self._session_id = session_id
        self._send_message = send_message
        self._answer_event.clear()

        # Start the signaling flow in a background task (non-blocking)
        self._signaling_task = self.hass.async_create_task(
            self._async_webrtc_signaling(offer_sdp)
        )

    async def _async_webrtc_signaling(self, offer_sdp: str) -> None:
        """Run WebRTC signaling flow (background task)."""
        try:
            # Step 1: Wake camera if sleeping (fire-and-forget per Pitfall 1)
            if self.coordinator.camera_state != CameraState.AWAKE:
                _LOGGER.debug(
                    "Camera not awake, sending wake command before WebRTC offer"
                )
                self.hass.async_create_task(
                    self.coordinator.async_wake_camera()
                )

            # Step 2: Fetch config
            await self._async_ensure_config()

            if not self._uid or not self._moto_id or not self._auth:
                self._send_error(
                    "WebRTC config incomplete (missing motoId, auth, or msid)"
                )
                return

            mqtt_client = self.coordinator.mqtt_client
            if mqtt_client is None or not mqtt_client.is_connected:
                self._send_error("MQTT not connected")
                return

            # Step 3: Generate signaling session ID (6-char, separate from HA's session_id)
            signaling_id = generate_session_id()
            self._signaling_id = signaling_id
            _LOGGER.debug(
                "WebRTC signaling session: %s (HA session: %s)",
                signaling_id,
                self._session_id,
            )

            # Step 4: Subscribe to answer/candidate topic
            subscribe_topic = WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE.format(
                msid=self._uid
            )
            publish_topic = WEBRTC_PUBLISH_TOPIC_TEMPLATE.format(
                moto_id=self._moto_id,
                device_id=self.coordinator.device_id,
            )

            # Register per-topic callback for WebRTC signaling messages
            mqtt_client.message_callback_add(
                subscribe_topic,
                lambda client, userdata, msg: self._on_signaling_message(
                    msg.payload, signaling_id
                ),
            )
            mqtt_client.subscribe(subscribe_topic, qos=1)
            _LOGGER.debug(
                "Subscribed to WebRTC signaling topic: %s", subscribe_topic
            )

            # Step 5: Strip extmap from SDP and build offer
            cleaned_sdp = strip_sdp_extmap(offer_sdp)
            offer_payload = build_offer_payload(
                sdp=cleaned_sdp,
                auth=self._auth,
                ice_servers=self._p2p_ices or [],
                stream_type=WEBRTC_STREAM_TYPE_HD,
            )
            offer_message = build_protocol_302_message(
                msg_type="offer",
                uid=self._uid,
                device_id=self.coordinator.device_id,
                session_id=signaling_id,
                moto_id=self._moto_id,
                msg_payload=offer_payload,
            )

            # Step 6: Publish offer to camera
            mqtt_client.publish(publish_topic, offer_message, qos=1)
            _LOGGER.debug(
                "Published WebRTC offer to %s (sdp_len=%d, cleaned_len=%d)",
                publish_topic,
                len(offer_sdp),
                len(cleaned_sdp),
            )

            # Step 7: Wait for SDP answer from camera
            try:
                await asyncio.wait_for(
                    self._answer_event.wait(),
                    timeout=WEBRTC_SESSION_TIMEOUT,
                )
            except TimeoutError:
                _LOGGER.warning(
                    "WebRTC SDP answer timed out after %ds",
                    WEBRTC_SESSION_TIMEOUT,
                )
                self._send_error("Camera did not respond with SDP answer")
                self._cleanup_signaling(subscribe_topic)
                return

            # Answer was received and forwarded in _on_signaling_message
            # ICE candidates continue to flow via the MQTT subscription
            _LOGGER.debug("WebRTC signaling complete, ICE candidates flowing")

        except Exception:
            _LOGGER.exception("WebRTC signaling failed")
            self._send_error("WebRTC signaling error")
            # Attempt cleanup
            try:
                subscribe_topic = WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE.format(
                    msid=self._uid or ""
                )
                self._cleanup_signaling(subscribe_topic)
            except Exception:
                _LOGGER.exception(
                    "Cleanup after signaling error also failed"
                )

    def _on_signaling_message(
        self, payload: bytes, signaling_id: str
    ) -> None:
        """Handle incoming MQTT protocol 302 message (answer or candidate).

        This callback runs on the asyncio event loop via paho AsyncioHelper.

        Args:
            payload: Raw MQTT payload bytes.
            signaling_id: The 6-char signaling session ID to filter by.
        """
        parsed = parse_protocol_302_message(payload, signaling_id)
        if parsed is None:
            return  # Not our session or not protocol 302

        msg_type = parsed["type"]
        msg_data = parsed["msg"]

        if msg_type == "answer" and self._send_message is not None:
            sdp = msg_data.get("sdp", "")
            _LOGGER.debug("Received WebRTC SDP answer (len=%d)", len(sdp))
            self._send_message(WebRTCAnswer(answer=sdp))
            self._answer_event.set()

        elif msg_type == "candidate" and self._send_message is not None:
            raw_candidate = msg_data.get("candidate", "")
            if raw_candidate:
                cleaned = clean_candidate_from_camera(raw_candidate)
                _LOGGER.debug(
                    "Received ICE candidate from camera: %s", cleaned[:60]
                )
                self._send_message(
                    WebRTCCandidate(RTCIceCandidateInit(candidate=cleaned))
                )

        elif msg_type == "disconnect":
            _LOGGER.debug("Camera sent disconnect signal")
            if self._uid:
                subscribe_topic = WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE.format(
                    msid=self._uid
                )
                self._cleanup_signaling(subscribe_topic)

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Forward browser ICE candidate to camera via MQTT protocol 302.

        Args:
            session_id: HA WebRTC session ID.
            candidate: ICE candidate from the browser.
        """
        if self._session_id != session_id:
            _LOGGER.debug(
                "Ignoring candidate for unknown session: %s", session_id
            )
            return

        if not self._uid or not self._moto_id or not self._signaling_id:
            _LOGGER.warning(
                "Cannot forward ICE candidate: config not loaded"
            )
            return

        mqtt_client = self.coordinator.mqtt_client
        if mqtt_client is None or not mqtt_client.is_connected:
            _LOGGER.warning(
                "Cannot forward ICE candidate: MQTT not connected"
            )
            return

        # Format candidate for camera (prepend "a=" prefix)
        formatted = format_candidate_for_camera(candidate.candidate)
        candidate_payload = build_candidate_payload(formatted)

        publish_topic = WEBRTC_PUBLISH_TOPIC_TEMPLATE.format(
            moto_id=self._moto_id,
            device_id=self.coordinator.device_id,
        )
        message = build_protocol_302_message(
            msg_type="candidate",
            uid=self._uid,
            device_id=self.coordinator.device_id,
            session_id=self._signaling_id,
            moto_id=self._moto_id,
            msg_payload=candidate_payload,
        )
        mqtt_client.publish(publish_topic, message, qos=1)
        _LOGGER.debug("Forwarded browser ICE candidate to camera")

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Clean up WebRTC session: send disconnect, unsubscribe MQTT, clear state.

        This is a synchronous callback (called by HA when frontend disconnects).
        paho-mqtt publish() is sync-safe (non-blocking, fire-and-forget).

        Args:
            session_id: HA WebRTC session ID to close.
        """
        if self._session_id != session_id:
            return

        _LOGGER.debug("Closing WebRTC session: %s", session_id)

        # Send disconnect message to camera via MQTT (sync-safe)
        mqtt_client = self.coordinator.mqtt_client
        if (
            mqtt_client is not None
            and mqtt_client.is_connected
            and self._uid
            and self._moto_id
            and self._signaling_id
        ):
            disconnect_payload = build_disconnect_payload()
            publish_topic = WEBRTC_PUBLISH_TOPIC_TEMPLATE.format(
                moto_id=self._moto_id,
                device_id=self.coordinator.device_id,
            )
            message = build_protocol_302_message(
                msg_type="disconnect",
                uid=self._uid,
                device_id=self.coordinator.device_id,
                session_id=self._signaling_id,
                moto_id=self._moto_id,
                msg_payload=disconnect_payload,
            )
            mqtt_client.publish(publish_topic, message, qos=0)

        # Unsubscribe from signaling topic
        if self._uid:
            subscribe_topic = WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE.format(
                msid=self._uid
            )
            self._cleanup_signaling(subscribe_topic)

    def _cleanup_signaling(self, subscribe_topic: str) -> None:
        """Remove MQTT subscription and reset session state.

        Args:
            subscribe_topic: The MQTT topic to unsubscribe from.
        """
        mqtt_client = self.coordinator.mqtt_client
        if mqtt_client is not None:
            try:
                mqtt_client.message_callback_remove(subscribe_topic)
                mqtt_client.unsubscribe(subscribe_topic)
            except Exception:
                _LOGGER.debug(
                    "Error during signaling cleanup", exc_info=True
                )

        # Cancel signaling task if still running
        if self._signaling_task is not None and not self._signaling_task.done():
            self._signaling_task.cancel()

        # Reset session state
        self._session_id = None
        self._send_message = None
        self._signaling_id = None
        self._signaling_task = None
        self._answer_event.clear()

    def _send_error(self, message: str) -> None:
        """Send WebRTC error to frontend via send_message callback.

        Args:
            message: Error message description.
        """
        if self._send_message is not None:
            self._send_message(
                WebRTCError("webrtc_offer_failed", message)
            )
        self._session_id = None
        self._send_message = None
        self._signaling_id = None

    @callback
    def async_get_webrtc_client_configuration(
        self,
    ) -> WebRTCClientConfiguration:
        """Provide Tuya's ICE servers to the browser PeerConnection.

        Returns TURN/STUN servers from p2pConfig.ices so the browser can
        establish a direct connection to the camera's relay.
        """
        ice_servers: list[RTCIceServer] = []
        if self._p2p_ices:
            for ice in self._p2p_ices:
                server = RTCIceServer(
                    urls=ice["urls"],
                    username=ice.get("username"),
                    credential=ice.get("credential"),
                )
                ice_servers.append(server)

        config = RTCConfiguration(ice_servers=ice_servers)
        return WebRTCClientConfiguration(configuration=config)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._session_id is not None:
            self.close_webrtc_session(self._session_id)
