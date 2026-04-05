"""WebRTC signaling helpers for MQTT protocol 302 (SDP/ICE exchange).

Source: go2rtc pkg/tuya/mqtt.go, client.go.
"""

from __future__ import annotations

import json
import logging
import random
import re
import string
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)


def generate_session_id() -> str:
    """Generate 6-char alphanumeric session ID (base-62, matching go2rtc core.RandString(6, 62))."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=6))


def strip_sdp_extmap(sdp: str) -> str:
    """Remove a=extmap lines from SDP to fit Tuya's 8KB MQTT payload limit.

    Source: go2rtc client.go regexp for "horter sdp, remove a=extmap... line,
    device ONLY allow 8KB json payload".
    """
    return re.sub(r"\r\na=extmap[^\r\n]*", "", sdp)


def clean_candidate_from_camera(raw_candidate: str) -> str:
    """Strip 'a=' prefix and '\\r\\n' suffix from camera ICE candidates for browser consumption.

    Source: go2rtc mqtt.go onMqttCandidate().
    """
    candidate = raw_candidate
    if candidate.startswith("a="):
        candidate = candidate[2:]
    candidate = candidate.rstrip("\r\n")
    return candidate


def format_candidate_for_camera(candidate: str) -> str:
    """Prepend 'a=' prefix to browser ICE candidates for camera consumption.

    Source: go2rtc mqtt.go SendCandidate().
    """
    if not candidate.startswith("a="):
        return f"a={candidate}"
    return candidate


def build_protocol_302_message(
    msg_type: str,
    uid: str,
    device_id: str,
    session_id: str,
    moto_id: str,
    msg_payload: dict[str, Any],
) -> bytes:
    """Build the full MQTT protocol 302 JSON envelope.

    Source: go2rtc mqtt.go sendMqttMessage().

    Args:
        msg_type: Message type ("offer", "answer", "candidate", "disconnect").
        uid: UID extracted from subscribe topic /av/u/{msid} -> msid.
        device_id: Target device ID.
        session_id: 6-char alphanumeric session ID.
        moto_id: Moto ID from jarvis/config.
        msg_payload: Inner message payload dict.

    Returns:
        JSON-encoded bytes with compact separators.
    """
    message = {
        "protocol": 302,
        "pv": "2.2",
        "t": int(time.time()),
        "data": {
            "header": {
                "type": msg_type,
                "from": uid,
                "to": device_id,
                "sub_dev_id": "",
                "sessionid": session_id,
                "moto_id": moto_id,
                "tid": "",
            },
            "msg": msg_payload,
        },
    }
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def build_offer_payload(
    sdp: str,
    auth: str,
    ice_servers: list[dict],
    stream_type: int = 0,
    datachannel_enable: bool = False,
) -> dict[str, Any]:
    """Build protocol 302 offer msg payload.

    Source: go2rtc mqtt.go SendOffer().

    Args:
        sdp: SDP offer string (extmap lines should be stripped before passing).
        auth: Auth token from jarvis/config.
        ice_servers: ICE server list from p2pConfig.ices.
        stream_type: Stream type (0=HD, 1=SD).
        datachannel_enable: Whether to enable datachannel (False for H.264).

    Returns:
        Offer payload dict for protocol 302 msg field.
    """
    return {
        "mode": "webrtc",
        "sdp": sdp,
        "stream_type": stream_type,
        "auth": auth,
        "datachannel_enable": datachannel_enable,
        "token": ice_servers,
    }


def build_candidate_payload(candidate: str) -> dict[str, Any]:
    """Build protocol 302 candidate msg payload.

    Args:
        candidate: ICE candidate string.

    Returns:
        Candidate payload dict for protocol 302 msg field.
    """
    return {
        "mode": "webrtc",
        "candidate": candidate,
    }


def build_disconnect_payload() -> dict[str, Any]:
    """Build protocol 302 disconnect msg payload.

    Returns:
        Disconnect payload dict for protocol 302 msg field.
    """
    return {
        "mode": "webrtc",
    }


def parse_protocol_302_message(
    payload: bytes, expected_session_id: str
) -> dict[str, Any] | None:
    """Parse incoming MQTT protocol 302 message.

    Returns None if not protocol 302 or wrong session.
    Source: go2rtc mqtt.go onMqttAnswer(), onMqttCandidate().

    Args:
        payload: Raw MQTT payload bytes.
        expected_session_id: Session ID to filter for.

    Returns:
        Dict with 'type' and 'msg' keys, or None if message should be ignored.
    """
    try:
        msg = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if msg.get("protocol") != 302:
        return None

    data = msg.get("data")
    if not data:
        return None

    header = data.get("header", {})
    if header.get("sessionid") != expected_session_id:
        _LOGGER.debug(
            "Ignoring protocol 302 message for session %s (expected %s)",
            header.get("sessionid"),
            expected_session_id,
        )
        return None

    msg_type = header.get("type", "")
    inner = data.get("msg", {})

    # Camera may send msg as JSON string or dict
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except (json.JSONDecodeError, ValueError):
            pass

    return {"type": msg_type, "msg": inner}
