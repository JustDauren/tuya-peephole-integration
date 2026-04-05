"""Tests for battery and signal strength sensor entities.

Requirements covered: SENS-02 (battery sensor), SENS-03 (signal strength sensor)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestTuyaBatterySensor:
    """Test TuyaBatterySensor entity."""

    def test_battery_sensor_device_class(self, mock_coordinator):
        """[SENS-02] Battery sensor has device_class=BATTERY."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor._attr_device_class == SensorDeviceClass.BATTERY

    def test_battery_sensor_state_class(self, mock_coordinator):
        """[SENS-02] Battery sensor has state_class=MEASUREMENT."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor
        from homeassistant.components.sensor import SensorStateClass

        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT

    def test_battery_sensor_unit(self, mock_coordinator):
        """[SENS-02] Battery sensor unit is %."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor._attr_native_unit_of_measurement == "%"

    def test_battery_sensor_unique_id(self, mock_coordinator):
        """Battery sensor unique_id is {device_id}_battery."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor._attr_unique_id == "test_device_id_abc123_battery"

    def test_battery_sensor_reads_coordinator_data(self, mock_coordinator):
        """[SENS-02] Battery sensor reads battery_percentage from coordinator data."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        mock_coordinator.data = {"battery_percentage": 85}
        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor.native_value == 85

    def test_battery_sensor_none_when_no_data(self, mock_coordinator):
        """Battery sensor returns None when coordinator has no data."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        mock_coordinator.data = None
        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor.native_value is None

    def test_battery_sensor_none_when_not_reported(self, mock_coordinator):
        """Battery sensor returns None when battery not yet reported."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        mock_coordinator.data = {"battery_percentage": None}
        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor.native_value is None

    def test_battery_sensor_exposes_events_as_attributes(self, mock_coordinator):
        """[HIST-02] Battery sensor exposes events as extra_state_attributes."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        events = [{"type": "motion", "time": 1700000000}]
        mock_coordinator.data = {"battery_percentage": 85, "last_events": events}
        sensor = TuyaBatterySensor(mock_coordinator)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert "events" in attrs
        assert attrs["events"] == events

    def test_battery_sensor_no_events_attribute_when_empty(self, mock_coordinator):
        """Battery sensor returns None for attributes when no events."""
        from custom_components.tuya_peephole.sensor import TuyaBatterySensor

        mock_coordinator.data = {"battery_percentage": 85, "last_events": []}
        sensor = TuyaBatterySensor(mock_coordinator)
        assert sensor.extra_state_attributes is None


class TestTuyaSignalStrengthSensor:
    """Test TuyaSignalStrengthSensor entity."""

    def test_signal_sensor_device_class(self, mock_coordinator):
        """[SENS-03] Signal sensor has device_class=SIGNAL_STRENGTH."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor._attr_device_class == SensorDeviceClass.SIGNAL_STRENGTH

    def test_signal_sensor_unit(self, mock_coordinator):
        """[SENS-03] Signal sensor unit is dBm."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor

        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor._attr_native_unit_of_measurement == "dBm"

    def test_signal_sensor_unique_id(self, mock_coordinator):
        """Signal sensor unique_id is {device_id}_signal_strength."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor

        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor._attr_unique_id == "test_device_id_abc123_signal_strength"

    def test_signal_sensor_reads_coordinator_data(self, mock_coordinator):
        """[SENS-03] Signal sensor reads signal_strength from coordinator data."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor

        mock_coordinator.data = {"signal_strength": -65}
        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor.native_value == -65

    def test_signal_sensor_disabled_by_default(self, mock_coordinator):
        """Signal sensor is disabled by default (diagnostic entity)."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor

        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor._attr_entity_registry_enabled_default is False

    def test_signal_sensor_none_when_no_data(self, mock_coordinator):
        """Signal sensor returns None when coordinator has no data."""
        from custom_components.tuya_peephole.sensor import TuyaSignalStrengthSensor

        mock_coordinator.data = None
        sensor = TuyaSignalStrengthSensor(mock_coordinator)
        assert sensor.native_value is None


class TestSensorSetupEntry:
    """Test sensor platform async_setup_entry."""

    @pytest.mark.asyncio
    async def test_sensor_setup_creates_both_entities(
        self, mock_hass_with_loop, mock_coordinator, mock_config_entry
    ):
        """async_setup_entry creates battery and signal sensors."""
        from custom_components.tuya_peephole.sensor import async_setup_entry
        from custom_components.tuya_peephole.const import DOMAIN

        mock_hass_with_loop.data = {
            DOMAIN: {mock_config_entry.entry_id: mock_coordinator}
        }
        mock_add_entities = MagicMock()

        await async_setup_entry(mock_hass_with_loop, mock_config_entry, mock_add_entities)

        mock_add_entities.assert_called_once()
        entities = mock_add_entities.call_args[0][0]
        assert len(entities) == 2
        names = {type(e).__name__ for e in entities}
        assert "TuyaBatterySensor" in names
        assert "TuyaSignalStrengthSensor" in names
