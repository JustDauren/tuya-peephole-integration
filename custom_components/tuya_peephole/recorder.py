"""Server-side WebRTC recording via aiortc.

Creates an independent RTCPeerConnection to the camera (separate from
the SDP proxy camera entity), receives H.264 video, and muxes to MP4
via aiortc's MediaRecorder. Uses existing MQTT protocol 302 signaling.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONTINUOUS_RECONNECT_MAX,
    CONTINUOUS_RECONNECT_MIN,
    MIN_FREE_SPACE_MB,
    RECORDING_DURATION,
    RECORDING_STORAGE_SUBDIR,
    RECORDING_WATCHDOG_MULTIPLIER,
    RETENTION_DAYS,
    WEBRTC_PUBLISH_TOPIC_TEMPLATE,
    WEBRTC_SESSION_TIMEOUT,
    WEBRTC_STREAM_TYPE_HD,
    WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE,
)
from .models import CameraState
from .webrtc_signaling import (
    build_disconnect_payload,
    build_offer_payload,
    build_protocol_302_message,
    generate_session_id,
    parse_protocol_302_message,
    strip_sdp_extmap,
)

if TYPE_CHECKING:
    from .coordinator import TuyaPeepholeCoordinator

# aiortc is an optional dependency -- may not be installed in all environments
try:
    from aiortc import (
        RTCConfiguration,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
    )
    from aiortc.contrib.media import MediaRecorder

    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False

_LOGGER = logging.getLogger(__name__)


class RecordingSession:
    """Server-side aiortc WebRTC session for recording camera video to MP4.

    Creates its own RTCPeerConnection (separate from the SDP proxy camera
    entity), negotiates SDP offer/answer via MQTT protocol 302, and muxes
    received H.264 video to an MP4 file via aiortc's MediaRecorder.
    """

    def __init__(
        self, coordinator: TuyaPeepholeCoordinator, output_path: str
    ) -> None:
        """Initialize recording session.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
            output_path: File path for the MP4 output (typically .tmp suffix).
        """
        self._coordinator = coordinator
        self._output_path = output_path
        self._pc: Any = None  # RTCPeerConnection (typed as Any for optional dep)
        self._recorder: Any = None  # MediaRecorder
        self._session_id: str | None = None
        self._answer_event = asyncio.Event()
        self._answer_sdp: str | None = None
        self._started = False
        self._stopped = False

        # MQTT signaling state
        self._subscribe_topic: str | None = None
        self._publish_topic: str | None = None

    async def async_start(self) -> bool:
        """Start the recording session: create PeerConnection, negotiate SDP, begin recording.

        Returns True if the session started successfully, False on any error.
        """
        if not AIORTC_AVAILABLE:
            _LOGGER.error(
                "aiortc is not installed -- cannot create recording session"
            )
            return False

        try:
            # Step 1: Fetch WebRTC config from Tuya API
            webrtc_config = (
                await self._coordinator.api.async_get_webrtc_config(
                    self._coordinator.device_id
                )
            )
            moto_id = webrtc_config["motoId"]
            auth = webrtc_config["auth"]
            p2p_ices = webrtc_config.get("p2pConfig", {}).get("ices", [])

            # Step 2: Fetch MQTT config for uid (msid)
            mqtt_config = await self._coordinator.api.async_get_mqtt_config(
                self._coordinator.device_id
            )
            uid = mqtt_config["msid"]

            # Step 3: Build ICE server configuration
            ice_servers = []
            for ice in p2p_ices:
                ice_servers.append(
                    RTCIceServer(
                        urls=ice["urls"],
                        username=ice.get("username"),
                        credential=ice.get("credential"),
                    )
                )

            config = RTCConfiguration(iceServers=ice_servers)

            # Step 4: Create PeerConnection and MediaRecorder
            self._pc = RTCPeerConnection(configuration=config)
            self._recorder = MediaRecorder(self._output_path, format="mp4")

            # Step 5: Add recvonly video transceiver
            self._pc.addTransceiver("video", direction="recvonly")

            # Step 6: Register track handler
            @self._pc.on("track")
            async def on_track(track: Any) -> None:
                if track.kind == "video":
                    _LOGGER.debug(
                        "Recording session received video track"
                    )
                    self._recorder.addTrack(track)
                    await self._recorder.start()

            # Step 7: Register connection state change handler
            @self._pc.on("connectionstatechange")
            async def on_state_change() -> None:
                state = self._pc.connectionState
                _LOGGER.debug(
                    "Recording PeerConnection state: %s", state
                )
                if state == "failed":
                    _LOGGER.warning(
                        "Recording PeerConnection failed, stopping session"
                    )
                    await self.async_stop()

            # Step 8: Create SDP offer
            offer = await self._pc.createOffer()
            await self._pc.setLocalDescription(offer)

            # Step 9: Generate signaling session ID
            self._session_id = generate_session_id()
            _LOGGER.debug(
                "Recording signaling session: %s", self._session_id
            )

            # Step 10: Subscribe to answer topic via MQTT
            mqtt_client = self._coordinator.mqtt_client
            if mqtt_client is None or not mqtt_client.is_connected:
                _LOGGER.error(
                    "Cannot start recording: MQTT not connected"
                )
                return False

            self._subscribe_topic = (
                WEBRTC_SUBSCRIBE_TOPIC_TEMPLATE.format(msid=uid)
            )
            self._publish_topic = WEBRTC_PUBLISH_TOPIC_TEMPLATE.format(
                moto_id=moto_id,
                device_id=self._coordinator.device_id,
            )

            # Register per-topic callback for signaling messages
            session_id = self._session_id
            mqtt_client._client.message_callback_add(
                self._subscribe_topic,
                lambda client, userdata, msg: self._on_signaling_message(
                    msg.payload
                ),
            )
            mqtt_client.subscribe(self._subscribe_topic, qos=1)

            # Step 11: Build and publish offer
            cleaned_sdp = strip_sdp_extmap(offer.sdp)
            offer_payload = build_offer_payload(
                sdp=cleaned_sdp,
                auth=auth,
                ice_servers=p2p_ices,
                stream_type=WEBRTC_STREAM_TYPE_HD,
            )
            offer_message = build_protocol_302_message(
                msg_type="offer",
                uid=uid,
                device_id=self._coordinator.device_id,
                session_id=session_id,
                moto_id=moto_id,
                msg_payload=offer_payload,
            )
            mqtt_client.publish(
                self._publish_topic, offer_message, qos=1
            )
            _LOGGER.debug(
                "Recording offer published to %s", self._publish_topic
            )

            # Step 12: Wait for SDP answer
            try:
                await asyncio.wait_for(
                    self._answer_event.wait(),
                    timeout=WEBRTC_SESSION_TIMEOUT,
                )
            except TimeoutError:
                _LOGGER.warning(
                    "Recording SDP answer timed out after %ds",
                    WEBRTC_SESSION_TIMEOUT,
                )
                return False

            # Step 13: Set remote description from received answer
            if self._answer_sdp is None:
                _LOGGER.error("Recording answer SDP is None after event")
                return False

            await self._pc.setRemoteDescription(
                RTCSessionDescription(
                    sdp=self._answer_sdp, type="answer"
                )
            )

            self._started = True
            _LOGGER.info(
                "Recording session started: %s", self._output_path
            )
            return True

        except Exception:
            _LOGGER.exception("Failed to start recording session")
            return False
        finally:
            if not self._started:
                await self.async_stop()

    def _on_signaling_message(self, payload: bytes) -> None:
        """Handle incoming MQTT protocol 302 message (answer or candidate).

        Args:
            payload: Raw MQTT payload bytes.
        """
        if self._session_id is None:
            return

        parsed = parse_protocol_302_message(payload, self._session_id)
        if parsed is None:
            return

        msg_type = parsed["type"]
        msg_data = parsed["msg"]

        if msg_type == "answer":
            sdp = msg_data.get("sdp", "")
            _LOGGER.debug(
                "Recording received SDP answer (len=%d)", len(sdp)
            )
            self._answer_sdp = sdp
            self._answer_event.set()

        elif msg_type == "candidate":
            # aiortc handles ICE gathering internally -- log and skip
            raw_candidate = msg_data.get("candidate", "")
            _LOGGER.debug(
                "Recording received ICE candidate (ignored, aiortc gathers internally): %s",
                raw_candidate[:60] if raw_candidate else "",
            )

    async def async_stop(self) -> None:
        """Stop the recording session and clean up resources."""
        if self._stopped:
            return
        self._stopped = True

        # Stop MediaRecorder
        if self._recorder is not None:
            try:
                await self._recorder.stop()
            except Exception:
                _LOGGER.debug(
                    "Error stopping MediaRecorder", exc_info=True
                )

        # Send disconnect via MQTT protocol 302
        mqtt_client = self._coordinator.mqtt_client
        if (
            mqtt_client is not None
            and mqtt_client.is_connected
            and self._publish_topic
            and self._session_id
        ):
            try:
                # Need uid and moto_id for disconnect message
                mqtt_config = (
                    await self._coordinator.api.async_get_mqtt_config(
                        self._coordinator.device_id
                    )
                )
                uid = mqtt_config["msid"]
                webrtc_config = (
                    await self._coordinator.api.async_get_webrtc_config(
                        self._coordinator.device_id
                    )
                )
                moto_id = webrtc_config["motoId"]

                disconnect_payload = build_disconnect_payload()
                message = build_protocol_302_message(
                    msg_type="disconnect",
                    uid=uid,
                    device_id=self._coordinator.device_id,
                    session_id=self._session_id,
                    moto_id=moto_id,
                    msg_payload=disconnect_payload,
                )
                mqtt_client.publish(self._publish_topic, message, qos=0)
            except Exception:
                _LOGGER.debug(
                    "Error sending recording disconnect", exc_info=True
                )

        # Remove MQTT callback and unsubscribe
        if (
            mqtt_client is not None
            and self._subscribe_topic is not None
        ):
            try:
                mqtt_client._client.message_callback_remove(
                    self._subscribe_topic
                )
                mqtt_client._client.unsubscribe(self._subscribe_topic)
            except Exception:
                _LOGGER.debug(
                    "Error during recording MQTT cleanup", exc_info=True
                )

        # Close PeerConnection
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception:
                _LOGGER.debug(
                    "Error closing recording PeerConnection",
                    exc_info=True,
                )

        _LOGGER.debug("Recording session stopped: %s", self._output_path)


class RecordingManager:
    """Manages recording lifecycle: motion triggers, file management, retention, and continuous mode.

    Owns the full lifecycle from motion trigger through file cleanup.
    Enforces single active session, disk space checks, and duration limits.
    Supports continuous recording mode when camera is on charger.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaPeepholeCoordinator,
    ) -> None:
        """Initialize the recording manager.

        Args:
            hass: Home Assistant instance.
            coordinator: The Tuya Peephole coordinator instance.
        """
        self._hass = hass
        self._coordinator = coordinator
        self._active_session: RecordingSession | None = None
        self._recording_task: asyncio.Task[Any] | None = None
        self._watchdog_unsub: Callable[..., None] | None = None
        self._stop_timer_unsub: Callable[..., None] | None = None
        self._cleanup_unsub: Callable[..., None] | None = None
        self._motion_unsub: Callable[..., None] | None = None
        self._continuous_task: asyncio.Task[Any] | None = None
        self._continuous_reconnect_delay = CONTINUOUS_RECONNECT_MIN
        self._storage_path = Path(
            hass.config.path(
                "media", RECORDING_STORAGE_SUBDIR, coordinator.device_id
            )
        )
        self._retention_days = RETENTION_DAYS
        self._duration = RECORDING_DURATION
        self._recording_enabled = True

    async def async_setup(self) -> None:
        """Set up the recording manager: create storage, register callbacks, schedule cleanup."""
        if not AIORTC_AVAILABLE:
            _LOGGER.warning(
                "aiortc not installed -- recording manager disabled"
            )
            return

        # Create storage directory
        await self._hass.async_add_executor_job(
            lambda: self._storage_path.mkdir(parents=True, exist_ok=True)
        )

        # Register motion callback
        self._motion_unsub = self._coordinator.register_motion_callback(
            self._on_motion_event
        )

        # Schedule daily retention cleanup
        self._cleanup_unsub = async_track_time_interval(
            self._hass,
            self._async_cleanup_recordings,
            timedelta(hours=24),
        )

        # Run initial cleanup
        self._hass.async_create_task(self._async_cleanup_recordings())

        _LOGGER.debug(
            "Recording manager set up, storage: %s", self._storage_path
        )

    def update_options(
        self, retention_days: int, duration: int, enabled: bool
    ) -> None:
        """Update recording options from OptionsFlow.

        Args:
            retention_days: Number of days to retain recordings.
            duration: Recording duration in seconds.
            enabled: Whether recording is enabled.
        """
        self._retention_days = retention_days
        self._duration = duration
        self._recording_enabled = enabled

    def _on_motion_event(self) -> None:
        """Handle motion event from coordinator -- schedule recording start."""
        if not self._recording_enabled:
            return
        self._hass.async_create_task(self.async_start_recording())

    async def async_start_recording(
        self, duration: int | None = None
    ) -> bool:
        """Start a recording session.

        Checks for active session, disk space, camera state, then creates
        a RecordingSession with .tmp output path.

        Args:
            duration: Recording duration in seconds (defaults to configured duration).

        Returns:
            True if recording started successfully.
        """
        if self._active_session is not None:
            _LOGGER.debug("Already recording, skipping")
            return False

        # Check disk space (blocking I/O via executor)
        try:
            usage = await self._hass.async_add_executor_job(
                shutil.disk_usage, str(self._storage_path)
            )
            if usage.free < MIN_FREE_SPACE_MB * 1024 * 1024:
                _LOGGER.warning(
                    "Insufficient disk space for recording: %dMB free (need %dMB)",
                    usage.free // (1024 * 1024),
                    MIN_FREE_SPACE_MB,
                )
                return False
        except OSError:
            _LOGGER.warning(
                "Cannot check disk space, skipping recording",
                exc_info=True,
            )
            return False

        # Wake camera if sleeping
        if self._coordinator.camera_state != CameraState.AWAKE:
            awoke = await self._coordinator.async_wake_camera()
            if not awoke:
                _LOGGER.warning(
                    "Cannot record: camera did not wake"
                )
                return False

        # Generate output file path with .tmp suffix for crash safety
        now = dt_util.now()
        date_dir = self._storage_path / now.strftime("%Y-%m-%d")
        await self._hass.async_add_executor_job(
            lambda: date_dir.mkdir(parents=True, exist_ok=True)
        )

        filename = (
            f"{self._coordinator.device_id}"
            f"_{now.strftime('%Y%m%d_%H%M%S')}.mp4"
        )
        final_path = date_dir / filename
        tmp_path = str(final_path) + ".tmp"

        # Create and start recording session
        session = RecordingSession(self._coordinator, tmp_path)
        started = await session.async_start()
        if not started:
            _LOGGER.warning("Recording session failed to start")
            return False

        self._active_session = session
        dur = duration or self._duration

        # Schedule stop after duration
        self._stop_timer_unsub = async_call_later(
            self._hass,
            dur,
            self._async_stop_recording_cb,
        )

        # Schedule watchdog at 2x duration to kill stale sessions
        self._watchdog_unsub = async_call_later(
            self._hass,
            dur * RECORDING_WATCHDOG_MULTIPLIER,
            self._async_watchdog_cb,
        )

        _LOGGER.info(
            "Recording started: %s (duration=%ds)", filename, dur
        )
        return True

    async def _async_stop_recording_cb(self, _now: Any = None) -> None:
        """Stop the active recording session (called by timer)."""
        # Cancel watchdog timer
        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
            self._watchdog_unsub = None

        # Cancel stop timer (in case called manually)
        if self._stop_timer_unsub is not None:
            self._stop_timer_unsub()
            self._stop_timer_unsub = None

        session = self._active_session
        if session is None:
            return

        self._active_session = None
        await session.async_stop()

        # Rename .tmp to .mp4 for crash safety (via executor for disk I/O)
        tmp_path = Path(session._output_path)

        async def _rename() -> None:
            def _do_rename() -> None:
                if tmp_path.exists():
                    final_path = Path(str(tmp_path).removesuffix(".tmp"))
                    tmp_path.rename(final_path)
                    _LOGGER.info(
                        "Recording saved: %s", final_path.name
                    )
                else:
                    _LOGGER.warning(
                        "Recording tmp file not found: %s", tmp_path
                    )

            await self._hass.async_add_executor_job(_do_rename)

        await _rename()

    async def _async_watchdog_cb(self, _now: Any = None) -> None:
        """Kill stale recording session (watchdog timer expired)."""
        if self._active_session is not None:
            _LOGGER.warning(
                "Recording watchdog triggered, killing stale session"
            )
            await self._async_stop_recording_cb()

    async def _async_cleanup_recordings(self, _now: Any = None) -> None:
        """Delete recordings older than retention period and remove empty date directories."""
        cutoff = dt_util.now() - timedelta(days=self._retention_days)
        storage = self._storage_path

        def _cleanup() -> int:
            deleted = 0
            if not storage.exists():
                return 0
            # Delete expired recordings
            for mp4 in storage.rglob("*.mp4"):
                try:
                    if mp4.stat().st_mtime < cutoff.timestamp():
                        mp4.unlink()
                        deleted += 1
                        _LOGGER.debug(
                            "Deleted expired recording: %s", mp4.name
                        )
                except OSError:
                    _LOGGER.debug(
                        "Error deleting recording: %s",
                        mp4,
                        exc_info=True,
                    )
            # Also clean up partial .tmp files older than cutoff
            for tmp in storage.rglob("*.tmp"):
                try:
                    if tmp.stat().st_mtime < cutoff.timestamp():
                        tmp.unlink()
                        _LOGGER.debug(
                            "Deleted partial recording: %s", tmp.name
                        )
                except OSError:
                    pass
            # Remove empty date directories
            for d in storage.iterdir():
                if d.is_dir():
                    try:
                        if not any(d.iterdir()):
                            d.rmdir()
                    except OSError:
                        pass
            return deleted

        deleted = await self._hass.async_add_executor_job(_cleanup)
        if deleted > 0:
            _LOGGER.info(
                "Retention cleanup: deleted %d expired recordings",
                deleted,
            )

    async def async_start_continuous(self) -> None:
        """Start continuous recording mode (for charging camera).

        Creates a background task that maintains a persistent recording
        session with exponential backoff reconnect on failures.
        """
        if self._continuous_task is not None:
            _LOGGER.debug("Continuous recording already running")
            return

        self._continuous_task = self._hass.async_create_task(
            self._continuous_recording_loop()
        )
        _LOGGER.info("Continuous recording mode started")

    async def _continuous_recording_loop(self) -> None:
        """Background loop for continuous recording with reconnect.

        Records in 1-hour segments to avoid huge files. Reconnects with
        exponential backoff on failures. Stops when camera is unplugged.
        """
        try:
            while self._coordinator.is_charging:
                try:
                    # Start a long recording session (1-hour segments)
                    started = await self.async_start_recording(
                        duration=3600
                    )
                    if started:
                        # Reset reconnect delay on success
                        self._continuous_reconnect_delay = (
                            CONTINUOUS_RECONNECT_MIN
                        )
                        # Wait for session to complete (timer will stop it)
                        while self._active_session is not None:
                            await asyncio.sleep(5)
                    else:
                        # Recording failed to start -- backoff and retry
                        _LOGGER.debug(
                            "Continuous recording: session failed, "
                            "retrying in %ds",
                            self._continuous_reconnect_delay,
                        )
                        await asyncio.sleep(
                            self._continuous_reconnect_delay
                        )
                        # Exponential backoff
                        self._continuous_reconnect_delay = min(
                            self._continuous_reconnect_delay * 2,
                            CONTINUOUS_RECONNECT_MAX,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception(
                        "Continuous recording loop error, "
                        "retrying in %ds",
                        self._continuous_reconnect_delay,
                    )
                    await asyncio.sleep(
                        self._continuous_reconnect_delay
                    )
                    self._continuous_reconnect_delay = min(
                        self._continuous_reconnect_delay * 2,
                        CONTINUOUS_RECONNECT_MAX,
                    )
        except asyncio.CancelledError:
            _LOGGER.debug("Continuous recording cancelled")
            # Stop any active session
            if self._active_session is not None:
                await self._async_stop_recording_cb()
        finally:
            self._continuous_task = None
            _LOGGER.info("Continuous recording mode stopped")

    async def async_stop_continuous(self) -> None:
        """Stop continuous recording mode."""
        if self._continuous_task is not None:
            self._continuous_task.cancel()
            try:
                await self._continuous_task
            except asyncio.CancelledError:
                pass
            self._continuous_task = None

        # Stop any active session
        if self._active_session is not None:
            await self._async_stop_recording_cb()

    async def async_teardown(self) -> None:
        """Clean up all recording manager resources."""
        # Stop continuous mode
        if self._continuous_task is not None:
            self._continuous_task.cancel()
            try:
                await self._continuous_task
            except asyncio.CancelledError:
                pass
            self._continuous_task = None

        # Stop active session
        if self._active_session is not None:
            await self._async_stop_recording_cb()

        # Cancel cleanup timer
        if self._cleanup_unsub is not None:
            self._cleanup_unsub()
            self._cleanup_unsub = None

        # Remove motion callback
        if self._motion_unsub is not None:
            self._motion_unsub()
            self._motion_unsub = None

        # Cancel watchdog
        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
            self._watchdog_unsub = None

        # Cancel stop timer
        if self._stop_timer_unsub is not None:
            self._stop_timer_unsub()
            self._stop_timer_unsub = None

        _LOGGER.debug("Recording manager teardown complete")
