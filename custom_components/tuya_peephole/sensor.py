"""Battery and signal strength sensors for the Tuya Peephole Camera integration.

Provides SensorDeviceClass.BATTERY and SensorDeviceClass.SIGNAL_STRENGTH
entities that read from coordinator push data (MQTT-driven, no polling).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TuyaPeepholeCoordinator
from .entity import TuyaPeepholeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tuya Peephole sensors from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being set up.
        async_add_entities: Callback to register new entities.
    """
    coordinator: TuyaPeepholeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TuyaBatterySensor(coordinator),
        TuyaSignalStrengthSensor(coordinator),
    ])


class TuyaBatterySensor(TuyaPeepholeEntity, SensorEntity):
    """Battery level sensor.

    Reports the camera battery percentage from MQTT push data.
    Updates via coordinator when battery_percentage is present in
    incoming MQTT messages.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: TuyaPeepholeCoordinator) -> None:
        """Initialize the battery sensor.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
        """
        super().__init__(coordinator, "battery", "Battery")

    @property
    def native_value(self) -> int | None:
        """Return battery percentage or None if not yet reported."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("battery_percentage")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return recent events from Tuya Message Center as attributes."""
        if self.coordinator.data is None:
            return None
        events = self.coordinator.data.get("last_events", [])
        if not events:
            return None
        return {"events": events}


class TuyaSignalStrengthSensor(TuyaPeepholeEntity, SensorEntity):
    """Wi-Fi signal strength (RSSI) sensor.

    Reports the camera Wi-Fi RSSI from MQTT push data.
    Disabled by default (diagnostic entity) -- user can enable
    from the entity settings in HA.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: TuyaPeepholeCoordinator) -> None:
        """Initialize the signal strength sensor.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
        """
        super().__init__(coordinator, "signal_strength", "Signal Strength")

    @property
    def native_value(self) -> int | None:
        """Return signal strength (RSSI in dBm) or None if not yet reported.

        Returns None if coordinator has no data yet (entity will show
        unknown state in HA until first MQTT update with signal data).
        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("signal_strength")
