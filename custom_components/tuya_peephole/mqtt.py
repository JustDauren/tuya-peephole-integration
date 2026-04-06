"""Async MQTT client for the Tuya Peephole Camera integration.

Uses paho-mqtt 2.1 with the AsyncioHelper pattern (socket callbacks)
to integrate MQTT I/O into the Home Assistant asyncio event loop
without background threads.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant

from .const import MQTT_CONNECT_TIMEOUT, MQTT_KEEPALIVE
from .exceptions import TuyaApiError
from .models import TuyaMQTTMessage

_LOGGER = logging.getLogger(__name__)


class TuyaMQTTClient:
    """Async MQTT client using the AsyncioHelper pattern.

    Integrates paho-mqtt into the asyncio event loop via socket callbacks
    (add_reader/add_writer), avoiding background threads. Uses paho-mqtt
    CallbackAPIVersion.VERSION2 for modern callback signatures.

    The client connects to Tuya's MQTT broker over TLS with certificate
    verification disabled (required for Tuya's broker). Automatic
    reconnection is handled by paho's built-in reconnect_delay_set with
    exponential backoff.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the MQTT client.

        Args:
            hass: Home Assistant instance for event loop access.
        """
        self._hass = hass
        self._loop = hass.loop
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=None,
            protocol=mqtt.MQTTv311,
        )
        self._connected = asyncio.Event()
        self._misc_task: asyncio.Task[None] | None = None

        # User-provided callbacks
        self._message_callback: Callable[[TuyaMQTTMessage], None] | None = None
        self._on_connected_callback: Callable[[], None] | None = None
        self._on_disconnected_callback: Callable[[], None] | None = None

    # --- AsyncioHelper socket callbacks ---
    # These integrate paho-mqtt's socket I/O into the asyncio event loop,
    # replacing the need for loop_start() / background thread.

    def _on_socket_open(
        self, client: mqtt.Client, userdata: Any, sock: Any
    ) -> None:
        """Register socket reader when paho opens its socket."""
        _LOGGER.debug("MQTT socket opened, registering reader")
        self._loop.add_reader(sock, client.loop_read)
        self._misc_task = self._loop.create_task(self._misc_loop())

    def _on_socket_close(
        self, client: mqtt.Client, userdata: Any, sock: Any
    ) -> None:
        """Remove socket reader when paho closes its socket."""
        _LOGGER.debug("MQTT socket closed, removing reader")
        self._loop.remove_reader(sock)
        if self._misc_task is not None:
            self._misc_task.cancel()
            self._misc_task = None

    def _on_socket_register_write(
        self, client: mqtt.Client, userdata: Any, sock: Any
    ) -> None:
        """Register socket writer when paho has data to send."""
        self._loop.add_writer(sock, client.loop_write)

    def _on_socket_unregister_write(
        self, client: mqtt.Client, userdata: Any, sock: Any
    ) -> None:
        """Remove socket writer when paho finishes sending."""
        self._loop.remove_writer(sock)

    async def _misc_loop(self) -> None:
        """Run paho's misc loop for keepalive and ping handling.

        This replaces loop_start()'s background thread. Runs until
        the client disconnects or the task is cancelled.
        """
        try:
            while self._client.loop_misc() == mqtt.MQTT_ERR_SUCCESS:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    # --- MQTT callbacks (VERSION2 signatures) ---

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """Handle successful or failed MQTT connection."""
        if reason_code == 0:
            _LOGGER.debug("MQTT connected to broker")
            self._connected.set()
            if self._on_connected_callback is not None:
                self._on_connected_callback()
        else:
            _LOGGER.error("MQTT connection failed: reason_code=%s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """Handle MQTT disconnection.

        Paho handles automatic reconnection via reconnect_delay_set.
        We clear the connected event and notify the coordinator.
        """
        self._connected.clear()
        _LOGGER.warning("MQTT disconnected: reason_code=%s", reason_code)
        if self._on_disconnected_callback is not None:
            self._on_disconnected_callback()

    def _on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        """Handle incoming MQTT message.

        Parses the raw payload into a TuyaMQTTMessage and forwards
        it to the registered message callback.
        """
        parsed = TuyaMQTTMessage.parse(msg.topic, msg.payload)
        # Log raw payload for debugging (first 200 chars)
        raw_preview = msg.payload[:200].decode("utf-8", errors="replace")
        _LOGGER.debug(
            "MQTT message on %s (len=%d): %s",
            msg.topic, len(msg.payload), raw_preview,
        )
        if self._message_callback is not None:
            self._message_callback(parsed)

    # --- Public API ---

    def set_message_callback(
        self, callback: Callable[[TuyaMQTTMessage], None]
    ) -> None:
        """Set callback for incoming MQTT messages.

        Args:
            callback: Function receiving parsed TuyaMQTTMessage instances.
        """
        self._message_callback = callback

    def set_on_connected_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for connection established events.

        Args:
            callback: Function called when MQTT connection is established.
        """
        self._on_connected_callback = callback

    def set_on_disconnected_callback(
        self, callback: Callable[[], None]
    ) -> None:
        """Set callback for disconnection events.

        Args:
            callback: Function called when MQTT connection is lost.
        """
        self._on_disconnected_callback = callback

    async def async_connect(
        self,
        broker: str,
        port: int,
        client_id: str,
        username: str,
        password: str,
    ) -> None:
        """Connect to the Tuya MQTT broker over TLS.

        Uses async_add_executor_job for the blocking connect() call
        to avoid blocking the event loop (paho's connect is synchronous).

        Args:
            broker: MQTT broker hostname.
            port: MQTT broker port (typically 8883 for TLS).
            client_id: MQTT client ID (web_{msid}).
            username: MQTT username (web_{msid}).
            password: MQTT password from /api/jarvis/mqtt.

        Raises:
            TuyaApiError: If connection times out or fails.
        """
        # Recreate client with correct client_id (avoid mutating private attrs)
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(username, password)

        # Configure TLS (Tuya broker requires CERT_NONE)
        # Use SSLContext directly — avoid ssl.create_default_context() which
        # does blocking disk I/O (loads system certs) and triggers HA detector
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        self._client.tls_set_context(ssl_ctx)

        # Register socket callbacks (AsyncioHelper pattern)
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = (
            self._on_socket_unregister_write
        )

        # Register MQTT callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Configure automatic reconnect with exponential backoff
        self._client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Connect in executor to avoid blocking event loop
        try:
            await self._hass.async_add_executor_job(
                self._client.connect, broker, port, MQTT_KEEPALIVE
            )
        except OSError as err:
            raise TuyaApiError(
                f"MQTT connection to {broker}:{port} failed: {err}"
            ) from err

        # Wait for on_connect callback
        try:
            await asyncio.wait_for(
                self._connected.wait(), timeout=MQTT_CONNECT_TIMEOUT
            )
        except TimeoutError as err:
            raise TuyaApiError(
                f"MQTT connection to {broker}:{port} timed out"
            ) from err

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe to an MQTT topic.

        Args:
            topic: Topic string to subscribe to.
            qos: Quality of Service level (0, 1, or 2).
        """
        self._client.subscribe(topic, qos)
        _LOGGER.debug("MQTT subscribed to %s (qos=%d)", topic, qos)

    def publish(self, topic: str, payload: bytes, qos: int = 0) -> None:
        """Publish a message to an MQTT topic.

        Args:
            topic: Topic string to publish to.
            payload: Message payload bytes.
            qos: Quality of Service level (0, 1, or 2).
        """
        self._client.publish(topic, payload, qos)
        _LOGGER.debug("MQTT published to %s (len=%d, qos=%d)", topic, len(payload), qos)

    def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from an MQTT topic.

        Args:
            topic: Topic string to unsubscribe from.
        """
        self._client.unsubscribe(topic)
        _LOGGER.debug("MQTT unsubscribed from %s", topic)

    def message_callback_add(
        self, topic: str, callback: Callable[..., None]
    ) -> None:
        """Add a per-topic message callback.

        Messages matching this topic will be routed to the callback
        instead of the default message handler.

        Args:
            topic: Topic filter string.
            callback: Callback function matching paho's on_message signature.
        """
        self._client.message_callback_add(topic, callback)

    def message_callback_remove(self, topic: str) -> None:
        """Remove a per-topic message callback.

        Args:
            topic: Topic filter to remove callback for.
        """
        self._client.message_callback_remove(topic)

    async def async_disconnect(self) -> None:
        """Disconnect from the MQTT broker and clean up resources."""
        _LOGGER.debug("MQTT disconnecting")
        self._client.disconnect()
        if self._misc_task is not None:
            self._misc_task.cancel()
            try:
                await self._misc_task
            except asyncio.CancelledError:
                pass
            self._misc_task = None

    @property
    def is_connected(self) -> bool:
        """Return True if connected to the MQTT broker."""
        return self._connected.is_set()
