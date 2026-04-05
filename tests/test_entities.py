"""Tests for entity platform modules: binary_sensor, button, and base entity.

Tests motion sensor state reading, wake button press, base entity DeviceInfo,
and MQTT-aware availability.

Requirements covered: SENS-01 (motion sensor), CTRL-01 (wake button), REL-01 (availability)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestTuyaPeepholeEntityBase:
    """Test TuyaPeepholeEntity base class."""

    def test_entity_unique_id(self, mock_coordinator) -> None:
        """Entity generates unique_id from coordinator.device_id and key."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity._attr_unique_id == "test_device_id_abc123_test_key"

    def test_entity_name(self, mock_coordinator) -> None:
        """Entity stores the provided name."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity._attr_name == "Test Name"

    def test_entity_has_entity_name(self, mock_coordinator) -> None:
        """Entity sets _attr_has_entity_name = True for HA naming."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity._attr_has_entity_name is True

    def test_entity_device_info(self, mock_coordinator) -> None:
        """Entity provides DeviceInfo with correct identifiers, manufacturer, model."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity
        from custom_components.tuya_peephole.const import DOMAIN

        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        info = entity._attr_device_info
        assert info.identifiers == {(DOMAIN, "test_device_id_abc123")}
        assert info.manufacturer == "Tuya"
        assert info.model == "Peephole Camera"
        # Name uses last 6 chars of device_id
        assert "abc123" in info.name

    def test_entity_available_when_mqtt_connected(
        self, mock_coordinator
    ) -> None:
        """[REL-01] Entity is available when MQTT client is connected."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        mock_coordinator.mqtt_client.is_connected = True
        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity.available is True

    def test_entity_unavailable_when_mqtt_disconnected(
        self, mock_coordinator
    ) -> None:
        """[REL-01] Entity is unavailable when MQTT client is disconnected."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        mock_coordinator.mqtt_client.is_connected = False
        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity.available is False

    def test_entity_unavailable_when_no_mqtt_client(
        self, mock_coordinator
    ) -> None:
        """[REL-01] Entity is unavailable when mqtt_client is None."""
        from custom_components.tuya_peephole.entity import TuyaPeepholeEntity

        mock_coordinator.mqtt_client = None
        entity = TuyaPeepholeEntity(mock_coordinator, "test_key", "Test Name")

        assert entity.available is False


class TestTuyaMotionSensor:
    """Test TuyaMotionSensor entity."""

    def test_motion_sensor_device_class_is_motion(
        self, mock_coordinator
    ) -> None:
        """[SENS-01] Motion sensor has device_class=MOTION."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass

        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor._attr_device_class == BinarySensorDeviceClass.MOTION

    def test_motion_sensor_unique_id(self, mock_coordinator) -> None:
        """Motion sensor unique_id is {device_id}_motion_detected."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor._attr_unique_id == "test_device_id_abc123_motion_detected"

    def test_motion_sensor_name(self, mock_coordinator) -> None:
        """Motion sensor name is 'Motion Detected'."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor._attr_name == "Motion Detected"

    def test_motion_sensor_is_on_when_motion_detected(
        self, mock_coordinator
    ) -> None:
        """[SENS-01] is_on returns True when coordinator reports motion_detected=True."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        mock_coordinator.data = {"motion_detected": True, "camera_state": "sleeping"}
        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor.is_on is True

    def test_motion_sensor_is_off_when_no_motion(
        self, mock_coordinator
    ) -> None:
        """[SENS-01] is_on returns False when coordinator reports motion_detected=False."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        mock_coordinator.data = {"motion_detected": False, "camera_state": "sleeping"}
        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor.is_on is False

    def test_motion_sensor_is_none_when_no_data(
        self, mock_coordinator
    ) -> None:
        """is_on returns None when coordinator has no data (shows 'unknown' in HA)."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        mock_coordinator.data = None
        sensor = TuyaMotionSensor(mock_coordinator)

        assert sensor.is_on is None

    def test_motion_sensor_available_depends_on_mqtt(
        self, mock_coordinator
    ) -> None:
        """Motion sensor availability follows base entity MQTT-aware logic."""
        from custom_components.tuya_peephole.binary_sensor import TuyaMotionSensor

        mock_coordinator.mqtt_client.is_connected = True
        sensor = TuyaMotionSensor(mock_coordinator)
        assert sensor.available is True

        mock_coordinator.mqtt_client.is_connected = False
        assert sensor.available is False


class TestTuyaWakeButton:
    """Test TuyaWakeButton entity."""

    def test_wake_button_icon(self, mock_coordinator) -> None:
        """[CTRL-01] Wake button has mdi:alarm-light-outline icon."""
        from custom_components.tuya_peephole.button import TuyaWakeButton

        button = TuyaWakeButton(mock_coordinator)

        assert button._attr_icon == "mdi:alarm-light-outline"

    def test_wake_button_unique_id(self, mock_coordinator) -> None:
        """Wake button unique_id is {device_id}_wake_camera."""
        from custom_components.tuya_peephole.button import TuyaWakeButton

        button = TuyaWakeButton(mock_coordinator)

        assert button._attr_unique_id == "test_device_id_abc123_wake_camera"

    def test_wake_button_name(self, mock_coordinator) -> None:
        """Wake button name is 'Wake Camera'."""
        from custom_components.tuya_peephole.button import TuyaWakeButton

        button = TuyaWakeButton(mock_coordinator)

        assert button._attr_name == "Wake Camera"

    @pytest.mark.asyncio
    async def test_wake_button_press_calls_coordinator(
        self, mock_coordinator
    ) -> None:
        """[CTRL-01] async_press() calls coordinator.async_wake_camera()."""
        from custom_components.tuya_peephole.button import TuyaWakeButton

        mock_coordinator.async_wake_camera = AsyncMock(return_value=True)
        button = TuyaWakeButton(mock_coordinator)

        await button.async_press()

        mock_coordinator.async_wake_camera.assert_awaited_once()

    def test_wake_button_always_available(
        self, mock_coordinator
    ) -> None:
        """[CTRL-01] Wake button is always available, even when MQTT disconnected."""
        from custom_components.tuya_peephole.button import TuyaWakeButton

        # MQTT connected
        mock_coordinator.mqtt_client.is_connected = True
        button = TuyaWakeButton(mock_coordinator)
        assert button.available is True

        # MQTT disconnected -- button should still be available
        mock_coordinator.mqtt_client.is_connected = False
        assert button.available is True

        # No MQTT client at all -- button should still be available
        mock_coordinator.mqtt_client = None
        assert button.available is True


class TestEntitySetupEntry:
    """Test async_setup_entry for entity platforms."""

    @pytest.mark.asyncio
    async def test_binary_sensor_setup_entry(
        self, mock_hass_with_loop, mock_coordinator, mock_config_entry
    ) -> None:
        """binary_sensor.async_setup_entry creates TuyaMotionSensor entity."""
        from custom_components.tuya_peephole.binary_sensor import async_setup_entry
        from custom_components.tuya_peephole.const import DOMAIN

        # Set up hass.data with coordinator
        mock_hass_with_loop.data = {
            DOMAIN: {mock_config_entry.entry_id: mock_coordinator}
        }

        mock_add_entities = MagicMock()

        await async_setup_entry(
            mock_hass_with_loop, mock_config_entry, mock_add_entities
        )

        mock_add_entities.assert_called_once()
        entities = mock_add_entities.call_args[0][0]
        assert len(entities) == 1
        assert type(entities[0]).__name__ == "TuyaMotionSensor"

    @pytest.mark.asyncio
    async def test_button_setup_entry(
        self, mock_hass_with_loop, mock_coordinator, mock_config_entry
    ) -> None:
        """button.async_setup_entry creates TuyaWakeButton and TuyaSnapshotButton."""
        from custom_components.tuya_peephole.button import async_setup_entry
        from custom_components.tuya_peephole.const import DOMAIN

        # Set up hass.data with coordinator
        mock_hass_with_loop.data = {
            DOMAIN: {mock_config_entry.entry_id: mock_coordinator}
        }

        mock_add_entities = MagicMock()

        await async_setup_entry(
            mock_hass_with_loop, mock_config_entry, mock_add_entities
        )

        mock_add_entities.assert_called_once()
        entities = mock_add_entities.call_args[0][0]
        assert len(entities) == 2
        names = {type(e).__name__ for e in entities}
        assert "TuyaWakeButton" in names
        assert "TuyaSnapshotButton" in names
