"""Base entity for the Tuya Peephole Camera integration.

Provides shared DeviceInfo, unique_id generation, and MQTT-aware
availability for all Tuya Peephole entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import TuyaPeepholeCoordinator


class TuyaPeepholeEntity(CoordinatorEntity["TuyaPeepholeCoordinator"]):
    """Base class for all Tuya Peephole Camera entities.

    Provides shared device identity so all entities appear under
    a single HA device, and MQTT-aware availability so entities
    go unavailable when MQTT is disconnected.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaPeepholeCoordinator,
        key: str,
        name: str,
    ) -> None:
        """Initialize the base entity.

        Args:
            coordinator: The Tuya Peephole coordinator instance.
            key: Entity key suffix for unique_id generation.
            name: Human-readable entity name.
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=f"Tuya Peephole {coordinator.device_id[-6:]}",
            manufacturer="Tuya",
            model="Peephole Camera",
        )

    @property
    def available(self) -> bool:
        """Return True if MQTT client is connected.

        Entities are gracefully unavailable when MQTT is disconnected
        (per REL-01: graceful when camera/MQTT unavailable).
        """
        return (
            self.coordinator.mqtt_client is not None
            and self.coordinator.mqtt_client.is_connected
        )
