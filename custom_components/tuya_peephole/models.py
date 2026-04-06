"""Data models for the Tuya Peephole Camera integration.

Contains CameraState enum for camera lifecycle tracking and
TuyaMQTTMessage parser for incoming MQTT payloads.
"""

from __future__ import annotations

import json
import logging
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class CameraState(Enum):
    """Camera lifecycle state (3-state model).

    SLEEPING: Camera is in low-power mode, not streaming.
    WAKING: Wake command sent, waiting for wireless_awake confirmation.
    AWAKE: Camera confirmed awake, ready for WebRTC streaming.
    """

    SLEEPING = "sleeping"
    WAKING = "waking"
    AWAKE = "awake"


class TuyaMQTTMessage:
    """Parser for incoming Tuya MQTT messages.

    Handles both JSON and binary payloads from the Tuya MQTT broker.
    Messages arrive on topic smart/decrypt/in/{device_id} and may
    contain wake confirmations, motion events, or WebRTC signaling.
    """

    def __init__(self, topic: str, payload: bytes) -> None:
        """Initialize message parser.

        Args:
            topic: MQTT topic the message was received on.
            payload: Raw message payload bytes.
        """
        self.topic = topic
        self.raw = payload
        self._text: str = payload.decode("utf-8", errors="replace")
        self._json: dict | None = None

        try:
            self._json = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    @classmethod
    def parse(cls, topic: str, payload: bytes) -> TuyaMQTTMessage:
        """Create a TuyaMQTTMessage from raw MQTT data.

        Args:
            topic: MQTT topic string.
            payload: Raw payload bytes.

        Returns:
            Parsed TuyaMQTTMessage instance.
        """
        return cls(topic, payload)

    @property
    def is_wireless_awake(self) -> bool:
        """Check if this message indicates the camera is awake.

        Some cameras send 'wireless_awake' explicitly.
        Others just send DPS updates (protocol 4) or events (protocol 56)
        when they're active — any such message means the camera is awake.
        """
        # Explicit wake confirmation
        if "wireless_awake" in self._text:
            return True
        # DPS update = camera is active and responding
        if self._json is not None:
            proto = self._json.get("protocol")
            if proto in (4, 56):
                return True
        return False

    @property
    def is_motion(self) -> bool:
        """Check if this message indicates a motion/PIR event.

        Detects motion via:
        - Protocol 56 with warnLevel (Tuya alarm/motion event)
        - DPS key 212 with door_lock_video (doorbell/peephole event)
        - PIR/alarm keywords in data dict or raw text
        """
        if self._json is not None:
            # Protocol 56 = alarm/motion event from Tuya
            if self._json.get("protocol") == 56:
                data = self._json.get("data", {})
                if isinstance(data, dict) and data.get("warnLevel"):
                    return True

            # DPS 212 with door_lock_video = doorbell press / motion capture
            data = self._json.get("data", {})
            if isinstance(data, dict):
                dps = data.get("dps", {})
                if isinstance(dps, dict):
                    dps_212 = dps.get("212", "")
                    if isinstance(dps_212, str) and "door_lock_video" in dps_212:
                        return True
                # Check data dict for motion-related keys
                for key in data:
                    if key in ("pir", "alarm_message", "movement_detect_pic"):
                        return True

        # Fallback: substring match in raw text
        text_lower = self._text.lower()
        return any(
            keyword in text_lower
            for keyword in ("pir", "alarm_message", "movement_detect_pic")
        )

    @property
    def battery_percentage(self) -> int | None:
        """Extract battery percentage from message data.

        Checks 'battery_percentage' and 'residual_electricity' (Tuya alternate key).
        Returns None if not present or not parseable. Clamped to 0-100.
        """
        if self._json is None:
            return None
        data = self._json.get("data")
        if not isinstance(data, dict):
            return None
        raw = data.get("battery_percentage")
        if raw is None:
            raw = data.get("residual_electricity")
        if raw is None:
            return None
        try:
            value = int(raw)
        except (ValueError, TypeError):
            return None
        return max(0, min(100, value))

    @property
    def signal_strength(self) -> int | None:
        """Extract signal strength (RSSI) from message data.

        Checks 'signal_strength' and 'wifi_signal' (Tuya alternate key).
        Returns None if not present or not parseable. No clamping (RSSI is negative).
        """
        if self._json is None:
            return None
        data = self._json.get("data")
        if not isinstance(data, dict):
            return None
        raw = data.get("signal_strength")
        if raw is None:
            raw = data.get("wifi_signal")
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    @property
    def json_data(self) -> dict | None:
        """Return parsed JSON data or None if payload is not JSON."""
        return self._json

    @property
    def is_protocol_302(self) -> bool:
        """Check if this message is a WebRTC signaling message (protocol 302)."""
        if self._json is None:
            return False
        return self._json.get("protocol") == 302

    @property
    def text(self) -> str:
        """Return decoded text representation of the payload."""
        return self._text

    def __repr__(self) -> str:
        """Return debug representation."""
        return (
            f"TuyaMQTTMessage(topic={self.topic!r}, "
            f"awake={self.is_wireless_awake}, "
            f"motion={self.is_motion}, "
            f"len={len(self.raw)})"
        )
