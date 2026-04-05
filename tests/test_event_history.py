"""Tests for event history (Message Center API).

Requirements covered: HIST-01 (retrieve events), HIST-02 (display events)
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMessageCenterAPI:
    """Test Tuya Message Center API method."""

    @pytest.mark.asyncio
    async def test_async_get_message_list_calls_api(self, api_client, mock_session):
        """[HIST-01] async_get_message_list posts to message center endpoint."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "success": True,
            "result": {
                "datas": [
                    {
                        "msgId": "1",
                        "msgTypeCode": "motion",
                        "msgTitle": "Motion detected",
                        "time": 1700000000,
                    },
                    {
                        "msgId": "2",
                        "msgTypeCode": "doorbell",
                        "msgTitle": "Doorbell pressed",
                        "time": 1700000100,
                    },
                ],
                "totalCount": 2,
            },
        })
        mock_response.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(
            return_value=mock_response
        )
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        events = await api_client.async_get_message_list(
            "test_device_id", limit=20
        )

        assert len(events) == 2
        assert events[0]["msgId"] == "1"
        assert events[1]["msgTypeCode"] == "doorbell"

    @pytest.mark.asyncio
    async def test_async_get_message_list_caches_results(
        self, api_client, mock_session
    ):
        """[HIST-01] Message list results are cached within TTL."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "success": True,
            "result": {
                "datas": [{"msgId": "1"}],
                "totalCount": 1,
            },
        })
        mock_response.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(
            return_value=mock_response
        )
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        # First call hits API
        await api_client.async_get_message_list("test_device_id")
        # Second call should use cache
        await api_client.async_get_message_list("test_device_id")

        # _post is called once (first call); second uses cache
        assert mock_session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_async_get_message_list_empty(self, api_client, mock_session):
        """Message list handles empty result."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "success": True,
            "result": {"datas": [], "totalCount": 0},
        })
        mock_response.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(
            return_value=mock_response
        )
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        # Invalidate cache from previous tests
        api_client.invalidate_cache()

        events = await api_client.async_get_message_list("test_device_id")
        assert events == []

    @pytest.mark.asyncio
    async def test_cache_invalidated_after_clear(self, api_client, mock_session):
        """Cache is cleared by invalidate_cache()."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "success": True,
            "result": {"datas": [{"msgId": "1"}], "totalCount": 1},
        })
        mock_response.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(
            return_value=mock_response
        )
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        # First call
        await api_client.async_get_message_list("test_device_id")
        # Invalidate
        api_client.invalidate_cache()
        # Second call should hit API again
        await api_client.async_get_message_list("test_device_id")

        assert mock_session.post.call_count == 2


class TestMQTTMessageBatterySignal:
    """Test TuyaMQTTMessage battery and signal parsing."""

    def test_battery_percentage_from_json(self):
        """[SENS-02] Parser extracts battery_percentage from MQTT JSON."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"battery_percentage": 85}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.battery_percentage == 85

    def test_battery_from_residual_electricity(self):
        """[SENS-02] Parser falls back to residual_electricity key."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"residual_electricity": 42}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.battery_percentage == 42

    def test_battery_clamped_to_100(self):
        """Battery percentage clamped to max 100."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"battery_percentage": 150}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.battery_percentage == 100

    def test_battery_clamped_to_0(self):
        """Battery percentage clamped to min 0."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"battery_percentage": -5}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.battery_percentage == 0

    def test_battery_none_when_missing(self):
        """Battery returns None when not in message."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        msg = TuyaMQTTMessage("test/topic", b'{"data": {"pir": "1"}}')
        assert msg.battery_percentage is None

    def test_signal_strength_from_json(self):
        """[SENS-03] Parser extracts signal_strength from MQTT JSON."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"signal_strength": -65}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.signal_strength == -65

    def test_signal_from_wifi_signal(self):
        """[SENS-03] Parser falls back to wifi_signal key."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        payload = json.dumps({"data": {"wifi_signal": -72}}).encode()
        msg = TuyaMQTTMessage("test/topic", payload)
        assert msg.signal_strength == -72

    def test_signal_none_when_missing(self):
        """Signal returns None when not in message."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        msg = TuyaMQTTMessage("test/topic", b'{"data": {"pir": "1"}}')
        assert msg.signal_strength is None

    def test_signal_none_on_binary_payload(self):
        """Signal returns None on non-JSON payload."""
        from custom_components.tuya_peephole.models import TuyaMQTTMessage

        msg = TuyaMQTTMessage("test/topic", b"\x00\x01\x02")
        assert msg.signal_strength is None
