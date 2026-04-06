"""Push-based DataUpdateCoordinator for the Tuya Peephole Camera integration.

Owns the MQTT client lifecycle and provides camera state management
including wake-up, motion detection, and graceful sleep handling.
No polling interval -- all updates are push-based from MQTT messages.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time as _time
import zlib
from collections.abc import Callable
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import TuyaSmartAPI
from .const import (
    CHARGING_STABLE_MINUTES,
    EVENT_HISTORY_LIMIT,
    MOTION_CLEAR_TIMEOUT,
    MQTT_PORT,
    WAKE_COOLDOWN,
    WAKE_TIMEOUT,
)
from .models import CameraState, TuyaMQTTMessage
from .mqtt import TuyaMQTTClient

_LOGGER = logging.getLogger(__name__)


class TuyaPeepholeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push-based coordinator owning the Tuya MQTT client lifecycle.

    Manages camera state transitions (SLEEPING/WAKING/AWAKE),
    processes MQTT messages for wake confirmations and motion events,
    and provides async_wake_camera for on-demand camera wake-up.

    No update_interval is set -- all data updates are pushed via
    async_set_updated_data when MQTT messages arrive.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: TuyaSmartAPI,
        device_id: str,
        local_key: str,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            api: Tuya Smart API client for MQTT config retrieval.
            device_id: Tuya device ID for topic routing.
            local_key: Device local key for CRC32 wake payload.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"Tuya Peephole {device_id}",
            # No update_interval -- push-only via MQTT
        )
        self.api = api
        self.device_id = device_id
        self.local_key = local_key

        self.mqtt_client: TuyaMQTTClient | None = None
        self._camera_state = CameraState.SLEEPING
        self._motion_detected = False
        self._battery_percentage: int | None = None
        self._signal_strength: int | None = None
        self._last_events: list[dict[str, Any]] = []
        self._motion_clear_unsub: CALLBACK_TYPE | None = None
        self._wake_cooldown = False
        self._awake_event = asyncio.Event()
        self._msid: str | None = None

        # Motion callback registration for recording manager
        self._on_motion_callbacks: list[Callable[[], None]] = []

        # Charging detection heuristic
        self._charging_detected = False
        self._battery_100_since: float | None = None  # monotonic time when battery first hit 100

    async def async_connect_mqtt(self) -> None:
        """Connect to Tuya MQTT broker.

        Fetches MQTT credentials from Tuya API, creates client,
        connects over TLS, and subscribes to device topics.
        Called explicitly from __init__.py async_setup_entry.
        """
        _LOGGER.debug("Fetching MQTT config for device %s", self.device_id)
        mqtt_config = await self.api.async_get_mqtt_config(self.device_id)
        msid = mqtt_config["msid"]
        mqtt_password = mqtt_config["password"]
        broker = self.api.mqtt_url

        _LOGGER.debug(
            "MQTT config: broker=%s, msid=%s..., client_id=web_%s...",
            broker, msid[:10], msid[:10],
        )

        self.mqtt_client = TuyaMQTTClient(self.hass)
        self.mqtt_client.set_message_callback(self._handle_mqtt_message)
        self.mqtt_client.set_on_connected_callback(self._handle_mqtt_connected)
        self.mqtt_client.set_on_disconnected_callback(
            self._handle_mqtt_disconnect
        )

        await self.mqtt_client.async_connect(
            broker=broker,
            port=MQTT_PORT,
            client_id=f"web_{msid}",
            username=f"web_{msid}",
            password=mqtt_password,
        )

        # Store msid for WebRTC signaling topic construction
        self._msid = msid
        _LOGGER.info("MQTT connected to %s, subscribing to topics", broker)

        # Subscribe to device messages
        self.mqtt_client.subscribe(
            f"smart/decrypt/in/{self.device_id}", qos=0
        )

    async def _async_setup(self) -> None:
        """Called by DataUpdateCoordinator — MQTT is already connected."""
        pass

    def _build_state_dict(self) -> dict[str, Any]:
        """Build the state dict pushed to all listening entities.

        Centralizes the coordinator data shape so all async_set_updated_data
        calls produce a consistent dict.
        """
        return {
            "camera_state": self._camera_state,
            "motion_detected": self._motion_detected,
            "battery_percentage": self._battery_percentage,
            "signal_strength": self._signal_strength,
            "last_events": self._last_events,
            "is_charging": self._charging_detected,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Return current state snapshot.

        This is called by DataUpdateCoordinator but since we are push-only,
        it simply returns the current state without fetching.
        """
        return self._build_state_dict()

    def _handle_mqtt_connected(self) -> None:
        """Handle MQTT connection established.

        Re-subscribes to device topic on reconnection.
        """
        if self.mqtt_client is not None:
            self.mqtt_client.subscribe(
                f"smart/decrypt/in/{self.device_id}", qos=0
            )
            _LOGGER.debug(
                "MQTT connected, subscribed to smart/decrypt/in/%s",
                self.device_id,
            )

    def _handle_mqtt_message(self, message: TuyaMQTTMessage) -> None:
        """Process an incoming MQTT message.

        NOTE: This may be called from the event loop (AsyncioHelper)
        or from a paho thread. Use call_soon_threadsafe for safety.
        """
        _LOGGER.debug(
            "Processing MQTT: topic=%s awake=%s motion=%s battery=%s signal=%s raw=%s",
            message.topic,
            message.is_wireless_awake,
            message.is_motion,
            message.battery_percentage,
            message.signal_strength,
            message.raw[:100].decode("utf-8", errors="replace") if message.raw else "",
        )

        if message.is_wireless_awake:
            self._camera_state = CameraState.AWAKE
            self._awake_event.set()
            _LOGGER.info("Camera wake confirmed via MQTT")

        if message.is_motion:
            self._motion_detected = True
            self._schedule_motion_clear()
            for cb in self._on_motion_callbacks:
                cb()

        if message.battery_percentage is not None:
            self._battery_percentage = message.battery_percentage
        if message.signal_strength is not None:
            self._signal_strength = message.signal_strength

        self._update_charging_state()

        # Push state update to all entities
        try:
            self.async_set_updated_data(self._build_state_dict())
        except RuntimeError:
            # If called from wrong thread, schedule on event loop
            self.hass.loop.call_soon_threadsafe(
                self.async_set_updated_data, self._build_state_dict()
            )

    def _schedule_motion_clear(self) -> None:
        """Schedule automatic motion detection clear after timeout.

        Cancels any existing timer and schedules a new one.
        Motion auto-clears after MOTION_CLEAR_TIMEOUT seconds.
        """
        if self._motion_clear_unsub is not None:
            self._motion_clear_unsub()
        self._motion_clear_unsub = async_call_later(
            self.hass, MOTION_CLEAR_TIMEOUT, self._async_clear_motion
        )

    @callback
    def _async_clear_motion(self, _now: Any) -> None:
        """Clear motion detection flag after timeout.

        Called automatically by async_call_later after MOTION_CLEAR_TIMEOUT.
        """
        self._motion_detected = False
        self._motion_clear_unsub = None
        self.async_set_updated_data(self._build_state_dict())

    async def async_wake_camera(self, force: bool = False) -> bool:
        """Send CRC32 wake packet to the camera via MQTT.

        Computes CRC32 of the local_key, packs as big-endian 4 bytes,
        and publishes to m/w/{device_id} with QoS 1. Waits up to
        WAKE_TIMEOUT seconds for wireless_awake confirmation.

        Args:
            force: If True, skip cooldown and AWAKE state checks.
                   Used by WebRTC to always send wake before offer.

        Returns:
            True if camera confirmed awake, False on timeout.
        """
        if not force:
            if self._wake_cooldown:
                _LOGGER.debug("Wake cooldown active, skipping wake request")
                return self._camera_state == CameraState.AWAKE

            if self._camera_state == CameraState.AWAKE:
                return True

        if self.mqtt_client is None or not self.mqtt_client.is_connected:
            _LOGGER.warning("Cannot wake camera: MQTT not connected")
            return False

        # Transition to WAKING state
        self._camera_state = CameraState.WAKING
        self._wake_cooldown = True
        self.async_set_updated_data(self._build_state_dict())

        # Compute CRC32 wake payload (big-endian 4 bytes)
        crc = zlib.crc32(self.local_key.encode()) & 0xFFFFFFFF
        wake_payload = struct.pack(">I", crc)
        wake_topic = f"m/w/{self.device_id}"

        # Clear event and publish wake command
        self._awake_event.clear()
        self.mqtt_client.publish(wake_topic, wake_payload, qos=1)
        _LOGGER.debug(
            "Wake packet sent: CRC32=%#010x to %s", crc, wake_topic
        )

        # Wait for wireless_awake confirmation
        try:
            await asyncio.wait_for(
                self._awake_event.wait(), timeout=WAKE_TIMEOUT
            )
            _LOGGER.debug("Camera confirmed awake")
            result = True
        except TimeoutError:
            _LOGGER.warning(
                "Camera wake timed out after %ds", WAKE_TIMEOUT
            )
            self._camera_state = CameraState.SLEEPING
            self.async_set_updated_data(self._build_state_dict())
            result = False

        # Schedule cooldown reset
        async_call_later(self.hass, WAKE_COOLDOWN, self._reset_cooldown)

        return result

    async def async_fetch_events(self) -> list[dict[str, Any]]:
        """Fetch recent events from Tuya Message Center API.

        Returns list of event dicts. Stores result in _last_events
        and includes in next push data update.
        """
        try:
            events = await self.api.async_get_message_list(
                self.device_id, limit=EVENT_HISTORY_LIMIT
            )
            self._last_events = events
            self.async_set_updated_data(self._build_state_dict())
            return events
        except Exception:
            _LOGGER.warning("Failed to fetch event history", exc_info=True)
            return self._last_events

    @callback
    def _reset_cooldown(self, _now: Any) -> None:
        """Reset the wake cooldown flag after WAKE_COOLDOWN seconds."""
        self._wake_cooldown = False

    def _handle_mqtt_disconnect(self) -> None:
        """Handle MQTT disconnection.

        Resets camera state to SLEEPING and invalidates API caches
        so MQTT credentials are refreshed on reconnection.
        """
        self._camera_state = CameraState.SLEEPING
        self._charging_detected = False
        self._battery_100_since = None
        self.api.invalidate_cache()
        _LOGGER.warning(
            "MQTT disconnected, camera state reset to SLEEPING"
        )
        self.async_set_updated_data(self._build_state_dict())

    async def async_teardown(self) -> None:
        """Clean up coordinator resources.

        Cancels motion clear timer and disconnects MQTT client.
        Must be called during config entry unload.
        """
        if self._motion_clear_unsub is not None:
            self._motion_clear_unsub()
            self._motion_clear_unsub = None

        if self.mqtt_client is not None:
            await self.mqtt_client.async_disconnect()
            self.mqtt_client = None

        _LOGGER.debug("Coordinator teardown complete for %s", self.device_id)

    def register_motion_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called on motion events.

        Returns an unsubscribe function.
        """
        self._on_motion_callbacks.append(callback)

        def _unsub() -> None:
            self._on_motion_callbacks.remove(callback)

        return _unsub

    def _update_charging_state(self) -> None:
        """Update charging state based on battery percentage heuristic.

        If battery_percentage == 100 for CHARGING_STABLE_MINUTES continuously,
        consider the camera on charger. If battery drops below 100, reset.
        """
        if self._battery_percentage == 100:
            if self._battery_100_since is None:
                self._battery_100_since = _time.monotonic()
            elif (
                _time.monotonic() - self._battery_100_since
            ) >= CHARGING_STABLE_MINUTES * 60:
                if not self._charging_detected:
                    self._charging_detected = True
                    _LOGGER.info("Charging detected (battery=100 sustained)")
        else:
            if self._charging_detected:
                self._charging_detected = False
                _LOGGER.info(
                    "Charger disconnected (battery dropped below 100)"
                )
            self._battery_100_since = None

    @property
    def is_charging(self) -> bool:
        """Return True if camera appears to be on charger."""
        return self._charging_detected

    @property
    def camera_state(self) -> CameraState:
        """Return the current camera lifecycle state."""
        return self._camera_state

    @property
    def msid(self) -> str | None:
        """Return the MQTT session ID (msid) for WebRTC signaling topic construction."""
        return self._msid
