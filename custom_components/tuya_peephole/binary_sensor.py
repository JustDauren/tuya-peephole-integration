"""Motion detection binary sensor for the Tuya Peephole Camera integration.

Provides a BinarySensorDeviceClass.MOTION entity that reads
motion_detected state from the coordinator's push data.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up Tuya Peephole motion binary sensor from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being set up.
        async_add_entities: Callback to register new entities.
    """
    coordinator: TuyaPeepholeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TuyaMotionSensor(coordinator)])


class TuyaMotionSensor(TuyaPeepholeEntity, BinarySensorEntity):
    """Motion detection binary sensor.

    Reports ON when the coordinator receives a PIR/motion event
    via MQTT, and automatically clears after MOTION_CLEAR_TIMEOUT.
    """

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, coordinator: TuyaPeepholeCoordinator) -> None:
        """Initialize the motion sensor.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
        """
        super().__init__(coordinator, "motion_detected", "Motion Detected")

    @property
    def is_on(self) -> bool | None:
        """Return True if motion is currently detected.

        Returns None if coordinator has no data yet (entity will show
        unknown state in HA until first MQTT update).
        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("motion_detected", False)
