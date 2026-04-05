"""Tests for TuyaMQTTClient (custom_components/tuya_peephole/mqtt.py).

Tests MQTT connection, subscription, publishing, message callback,
and disconnection using mocked paho-mqtt client.

Requirements covered: MQTT-01 (connect), MQTT-03 (message parse), MQTT-04 (reconnect)
"""

from __future__ import annotations

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTuyaMQTTClientInit:
    """Test TuyaMQTTClient initialization."""

    def test_mqtt_client_creates_paho_client_with_version2(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] Client creates paho.Client with CallbackAPIVersion.VERSION2 and MQTTv311."""
        import paho.mqtt.client as mqtt

        with patch.object(mqtt, "Client", wraps=mqtt.Client) as mock_client_cls:
            from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

            client = TuyaMQTTClient(mock_hass_with_loop)

            mock_client_cls.assert_called_once_with(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=None,
                protocol=mqtt.MQTTv311,
            )

    def test_mqtt_client_initial_state(self, mock_hass_with_loop) -> None:
        """Client starts disconnected with no callbacks set."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)

        assert client.is_connected is False
        assert client._message_callback is None
        assert client._misc_task is None


class TestTuyaMQTTClientConnect:
    """Test TuyaMQTTClient connection."""

    @pytest.mark.asyncio
    async def test_mqtt_connect_sets_tls_context(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] Connect sets TLS context with check_hostname=False and CERT_NONE."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)

        # Mock paho client methods
        client._client = MagicMock()
        client._connected = MagicMock()
        client._connected.wait = AsyncMock()

        await client.async_connect(
            broker="m1-eu.iot334.com",
            port=8883,
            client_id="web_test_msid",
            username="web_test_msid",
            password="testpass",
        )

        # Verify tls_set_context was called
        client._client.tls_set_context.assert_called_once()
        ssl_ctx = client._client.tls_set_context.call_args[0][0]
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.check_hostname is False
        assert ssl_ctx.verify_mode == ssl.CERT_NONE

    @pytest.mark.asyncio
    async def test_mqtt_connect_sets_credentials(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] Connect sets MQTT username and password."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()
        client._connected = MagicMock()
        client._connected.wait = AsyncMock()

        await client.async_connect(
            broker="m1-eu.iot334.com",
            port=8883,
            client_id="web_test_msid",
            username="web_test_msid",
            password="testpass",
        )

        client._client.username_pw_set.assert_called_once_with(
            "web_test_msid", "testpass"
        )

    @pytest.mark.asyncio
    async def test_mqtt_connect_uses_executor_job(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] Connect uses async_add_executor_job for blocking connect()."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()
        client._connected = MagicMock()
        client._connected.wait = AsyncMock()

        await client.async_connect(
            broker="m1-eu.iot334.com",
            port=8883,
            client_id="web_test_msid",
            username="web_test_msid",
            password="testpass",
        )

        mock_hass_with_loop.async_add_executor_job.assert_awaited_once()
        call_args = mock_hass_with_loop.async_add_executor_job.call_args[0]
        # First arg is the blocking function (client.connect)
        assert call_args[0] == client._client.connect
        # Remaining args: broker, port, keepalive
        assert call_args[1] == "m1-eu.iot334.com"
        assert call_args[2] == 8883

    @pytest.mark.asyncio
    async def test_mqtt_connect_sets_reconnect_delay(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-04] Connect sets reconnect_delay_set(min_delay=1, max_delay=120)."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()
        client._connected = MagicMock()
        client._connected.wait = AsyncMock()

        await client.async_connect(
            broker="m1-eu.iot334.com",
            port=8883,
            client_id="web_test_msid",
            username="web_test_msid",
            password="testpass",
        )

        client._client.reconnect_delay_set.assert_called_once_with(
            min_delay=1, max_delay=120
        )

    @pytest.mark.asyncio
    async def test_mqtt_connect_registers_socket_callbacks(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] Connect registers AsyncioHelper socket callbacks on paho client."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()
        client._connected = MagicMock()
        client._connected.wait = AsyncMock()

        await client.async_connect(
            broker="m1-eu.iot334.com",
            port=8883,
            client_id="web_test_msid",
            username="web_test_msid",
            password="testpass",
        )

        # Verify socket callbacks are set
        assert client._client.on_socket_open is not None
        assert client._client.on_socket_close is not None
        assert client._client.on_socket_register_write is not None
        assert client._client.on_socket_unregister_write is not None


class TestTuyaMQTTClientOperations:
    """Test subscribe, publish, and message operations."""

    def test_mqtt_subscribe_calls_paho(self, mock_hass_with_loop) -> None:
        """Subscribe calls paho client.subscribe with topic and qos."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()

        client.subscribe("smart/decrypt/in/test_device", qos=1)

        client._client.subscribe.assert_called_once_with(
            "smart/decrypt/in/test_device", 1
        )

    def test_mqtt_publish_calls_paho(self, mock_hass_with_loop) -> None:
        """Publish calls paho client.publish with topic, payload, qos."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()

        payload = b"\x62\xfb\xb9\x46"
        client.publish("m/w/test_device", payload, qos=1)

        client._client.publish.assert_called_once_with(
            "m/w/test_device", payload, 1
        )

    def test_mqtt_message_callback_invoked(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-03] on_message parses payload and invokes user callback with TuyaMQTTMessage."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)

        # Register callback
        callback = MagicMock()
        client.set_message_callback(callback)

        # Simulate paho on_message with a mock MQTTMessage
        mock_msg = MagicMock()
        mock_msg.topic = "smart/decrypt/in/test_device"
        mock_msg.payload = b'{"data":{"wireless_awake":true}}'

        client._on_message(client._client, None, mock_msg)

        callback.assert_called_once()
        parsed_msg = callback.call_args[0][0]
        assert parsed_msg.topic == "smart/decrypt/in/test_device"
        assert parsed_msg.is_wireless_awake is True

    def test_mqtt_message_callback_motion(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-03] on_message correctly identifies motion events."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)

        callback = MagicMock()
        client.set_message_callback(callback)

        mock_msg = MagicMock()
        mock_msg.topic = "smart/decrypt/in/test_device"
        mock_msg.payload = b'{"data":{"pir":"1"}}'

        client._on_message(client._client, None, mock_msg)

        parsed_msg = callback.call_args[0][0]
        assert parsed_msg.is_motion is True
        assert parsed_msg.is_wireless_awake is False


class TestTuyaMQTTClientDisconnect:
    """Test MQTT client disconnection."""

    @pytest.mark.asyncio
    async def test_mqtt_disconnect_cleans_up(
        self, mock_hass_with_loop
    ) -> None:
        """Disconnect calls paho disconnect and cancels misc_task."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()

        # Create a real asyncio task that we can cancel
        async def _noop():
            await asyncio.sleep(100)

        real_task = asyncio.create_task(_noop())
        client._misc_task = real_task

        await client.async_disconnect()

        client._client.disconnect.assert_called_once()
        assert real_task.cancelled()
        assert client._misc_task is None

    @pytest.mark.asyncio
    async def test_mqtt_disconnect_without_misc_task(
        self, mock_hass_with_loop
    ) -> None:
        """Disconnect works when no misc_task is running."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient

        client = TuyaMQTTClient(mock_hass_with_loop)
        client._client = MagicMock()
        client._misc_task = None

        await client.async_disconnect()

        client._client.disconnect.assert_called_once()


class TestTuyaMQTTClientCallbacks:
    """Test MQTT connection/disconnection callbacks."""

    def test_on_connect_sets_connected_event(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-01] on_connect sets the connected event on success."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient
        import paho.mqtt.client as mqtt

        client = TuyaMQTTClient(mock_hass_with_loop)

        # Simulate on_connect with reason_code=0 (success)
        reason_code = mqtt.ReasonCode(0)
        flags = mqtt.ConnectFlags()
        client._on_connect(client._client, None, flags, reason_code, None)

        assert client.is_connected is True

    def test_on_connect_invokes_callback(
        self, mock_hass_with_loop
    ) -> None:
        """on_connect invokes the user-provided connected callback."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient
        import paho.mqtt.client as mqtt

        client = TuyaMQTTClient(mock_hass_with_loop)
        connected_cb = MagicMock()
        client.set_on_connected_callback(connected_cb)

        reason_code = mqtt.ReasonCode(0)
        flags = mqtt.ConnectFlags()
        client._on_connect(client._client, None, flags, reason_code, None)

        connected_cb.assert_called_once()

    def test_on_disconnect_clears_connected_event(
        self, mock_hass_with_loop
    ) -> None:
        """[MQTT-04] on_disconnect clears the connected event."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient
        import paho.mqtt.client as mqtt

        client = TuyaMQTTClient(mock_hass_with_loop)

        # First connect
        client._connected.set()
        assert client.is_connected is True

        # Then disconnect
        reason_code = mqtt.ReasonCode(0)
        flags = mqtt.DisconnectFlags()
        client._on_disconnect(client._client, None, flags, reason_code, None)

        assert client.is_connected is False

    def test_on_disconnect_invokes_callback(
        self, mock_hass_with_loop
    ) -> None:
        """on_disconnect invokes the user-provided disconnected callback."""
        from custom_components.tuya_peephole.mqtt import TuyaMQTTClient
        import paho.mqtt.client as mqtt

        client = TuyaMQTTClient(mock_hass_with_loop)
        disconnected_cb = MagicMock()
        client.set_on_disconnected_callback(disconnected_cb)

        reason_code = mqtt.ReasonCode(0)
        flags = mqtt.DisconnectFlags()
        client._on_disconnect(client._client, None, flags, reason_code, None)

        disconnected_cb.assert_called_once()
