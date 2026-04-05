"""Tests for tuya_peephole media_source.py (TuyaPeepholeMediaSource).

Tests the media source platform: root browsing, device listing,
date browsing with descending sort, clip listing with .tmp filtering,
and media resolution for MP4 playback.

Requirements covered: REC-04
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass_media(tmp_path):
    """Create a mock hass with media directory for media source tests."""
    hass = MagicMock()
    media_dir = tmp_path / "media" / "tuya_peephole"
    media_dir.mkdir(parents=True)
    hass.config.path = MagicMock(
        side_effect=lambda *args: str(tmp_path / Path(*args))
    )
    hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args) if args else fn()
    )
    return hass, media_dir


# ---------------------------------------------------------------------------
# Browse tests
# ---------------------------------------------------------------------------


class TestMediaSourceBrowse:
    """Test TuyaPeepholeMediaSource browsing at all hierarchy levels."""

    @pytest.mark.asyncio
    async def test_browse_root_empty(self, mock_hass_media) -> None:
        """Root browse returns empty children when no recordings exist."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = None

        result = await source.async_browse_media(item)

        assert result.title == "Tuya Peephole Recordings"
        assert result.children == []
        assert result.can_expand is True
        assert result.can_play is False

    @pytest.mark.asyncio
    async def test_browse_root_with_device(self, mock_hass_media) -> None:
        """Root browse returns device directory as child."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        device_dir = media_dir / "abc123"
        device_dir.mkdir()

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = None

        result = await source.async_browse_media(item)

        assert len(result.children) == 1
        child = result.children[0]
        assert child.identifier == "abc123"
        assert child.title == "Camera abc123"
        assert child.can_expand is True
        assert child.can_play is False

    @pytest.mark.asyncio
    async def test_browse_device_dates(self, mock_hass_media) -> None:
        """Device browse returns date directories sorted descending."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        device_dir = media_dir / "abc123"
        (device_dir / "2026-04-01").mkdir(parents=True)
        (device_dir / "2026-04-03").mkdir()
        (device_dir / "2026-04-02").mkdir()

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "abc123"

        result = await source.async_browse_media(item)

        assert len(result.children) == 3
        # Should be sorted descending (newest first)
        assert result.children[0].title == "2026-04-03"
        assert result.children[1].title == "2026-04-02"
        assert result.children[2].title == "2026-04-01"
        # All should be expandable directories
        for child in result.children:
            assert child.can_expand is True
            assert child.can_play is False

    @pytest.mark.asyncio
    async def test_browse_date_clips(self, mock_hass_media) -> None:
        """Date browse returns MP4 files as playable children sorted descending."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        date_dir = media_dir / "abc123" / "2026-04-05"
        date_dir.mkdir(parents=True)
        (date_dir / "abc123_20260405_120000.mp4").write_text("video1")
        (date_dir / "abc123_20260405_143000.mp4").write_text("video2")
        (date_dir / "abc123_20260405_090000.mp4").write_text("video3")

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "abc123/2026-04-05"

        result = await source.async_browse_media(item)

        assert len(result.children) == 3
        # Should be sorted descending by filename (newest first)
        assert result.children[0].title == "14:30:00"
        assert result.children[1].title == "12:00:00"
        assert result.children[2].title == "09:00:00"
        # All should be playable
        for child in result.children:
            assert child.can_play is True
            assert child.can_expand is False

    @pytest.mark.asyncio
    async def test_browse_date_ignores_tmp_files(self, mock_hass_media) -> None:
        """Date browse only shows .mp4 files, not .tmp or other extensions."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        date_dir = media_dir / "abc123" / "2026-04-05"
        date_dir.mkdir(parents=True)
        (date_dir / "abc123_20260405_120000.mp4").write_text("video1")
        (date_dir / "abc123_20260405_130000.mp4.tmp").write_text("partial")
        (date_dir / "abc123_20260405_140000.txt").write_text("not video")

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "abc123/2026-04-05"

        result = await source.async_browse_media(item)

        # Only the .mp4 file should be listed
        assert len(result.children) == 1
        assert result.children[0].title == "12:00:00"

    @pytest.mark.asyncio
    async def test_browse_empty_device(self, mock_hass_media) -> None:
        """Device browse with no date directories returns empty children."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        device_dir = media_dir / "abc123"
        device_dir.mkdir()

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "abc123"

        result = await source.async_browse_media(item)

        assert result.children == []
        assert result.title == "Camera abc123"

    @pytest.mark.asyncio
    async def test_browse_multiple_devices(self, mock_hass_media) -> None:
        """Root browse with multiple devices lists all sorted descending."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        (media_dir / "device_aaa").mkdir()
        (media_dir / "device_zzz").mkdir()
        (media_dir / "device_mmm").mkdir()

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = None

        result = await source.async_browse_media(item)

        assert len(result.children) == 3
        # Sorted descending
        titles = [c.title for c in result.children]
        assert titles == ["Camera device_zzz", "Camera device_mmm", "Camera device_aaa"]


# ---------------------------------------------------------------------------
# Resolve tests
# ---------------------------------------------------------------------------


class TestMediaSourceResolve:
    """Test TuyaPeepholeMediaSource media resolution."""

    @pytest.mark.asyncio
    async def test_resolve_media_returns_play_media(
        self, mock_hass_media
    ) -> None:
        """Resolve returns PlayMedia with correct URL and mime_type."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        # Create the actual file so is_file returns True
        file_dir = media_dir / "abc123" / "2026-04-05"
        file_dir.mkdir(parents=True)
        (file_dir / "abc123_20260405_120000.mp4").write_text("video")

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "abc123/2026-04-05/abc123_20260405_120000.mp4"

        result = await source.async_resolve_media(item)

        assert result.url == "/media/tuya_peephole/abc123/2026-04-05/abc123_20260405_120000.mp4"
        assert result.mime_type == "video/mp4"

    @pytest.mark.asyncio
    async def test_resolve_media_path_construction(
        self, mock_hass_media
    ) -> None:
        """Resolve constructs path via hass.config.path with correct arguments."""
        from custom_components.tuya_peephole.media_source import (
            async_get_media_source,
        )

        hass, media_dir = mock_hass_media
        # Create the actual file
        file_dir = media_dir / "device1" / "2026-04-01"
        file_dir.mkdir(parents=True)
        (file_dir / "device1_20260401_100000.mp4").write_text("video")

        source = await async_get_media_source(hass)

        item = MagicMock()
        item.identifier = "device1/2026-04-01/device1_20260401_100000.mp4"

        result = await source.async_resolve_media(item)

        # Verify config.path was called with expected arguments
        hass.config.path.assert_called_with(
            "media", "tuya_peephole", "device1/2026-04-01/device1_20260401_100000.mp4"
        )


# ---------------------------------------------------------------------------
# Format filename title tests
# ---------------------------------------------------------------------------


class TestFilenameTitle:
    """Test the _format_filename_title static method."""

    def test_format_standard_filename(self) -> None:
        """Standard filename is formatted as HH:MM:SS."""
        from custom_components.tuya_peephole.media_source import (
            TuyaPeepholeMediaSource,
        )

        assert TuyaPeepholeMediaSource._format_filename_title(
            "abc123_20260405_120000.mp4"
        ) == "12:00:00"

    def test_format_filename_afternoon(self) -> None:
        """Afternoon time is formatted correctly."""
        from custom_components.tuya_peephole.media_source import (
            TuyaPeepholeMediaSource,
        )

        assert TuyaPeepholeMediaSource._format_filename_title(
            "abc123_20260405_235959.mp4"
        ) == "23:59:59"

    def test_format_fallback_nonstandard_filename(self) -> None:
        """Non-standard filename returns raw filename as fallback."""
        from custom_components.tuya_peephole.media_source import (
            TuyaPeepholeMediaSource,
        )

        result = TuyaPeepholeMediaSource._format_filename_title("random_file.mp4")
        assert result == "random_file.mp4"
