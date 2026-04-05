"""Media source platform for browsing Tuya Peephole camera recordings.

Exposes local MP4 recordings in the HA media browser with a
date-based hierarchy: root -> date folders -> individual clips.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, RECORDING_STORAGE_SUBDIR

_LOGGER = logging.getLogger(__name__)


async def async_get_media_source(hass: HomeAssistant) -> TuyaPeepholeMediaSource:
    """Set up Tuya Peephole media source."""
    return TuyaPeepholeMediaSource(hass)


class TuyaPeepholeMediaSource(MediaSource):
    """Provide Tuya Peephole recordings as a media source for the HA media browser."""

    name = "Tuya Peephole Recordings"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable URL.

        Args:
            item: MediaSourceItem with identifier format
                  "{device_id}/{date}/{filename}".

        Returns:
            PlayMedia with local media URL and video/mp4 mime type.
        """
        # Validate the file exists
        full_path = Path(
            self.hass.config.path(
                "media", RECORDING_STORAGE_SUBDIR, item.identifier
            )
        )
        if not await self.hass.async_add_executor_job(full_path.is_file):
            raise BrowseError(  # noqa: F821 -- HA raises this from media_source
                f"Recording not found: {item.identifier}"
            )

        return PlayMedia(
            url=f"/media/{RECORDING_STORAGE_SUBDIR}/{item.identifier}",
            mime_type="video/mp4",
        )

    async def async_browse_media(
        self, item: MediaSourceItem
    ) -> BrowseMediaSource:
        """Browse recordings in a date-based hierarchy.

        Hierarchy:
          - Root (no identifier): lists device_id directories
          - 1 part (device_id): lists date subdirectories
          - 2 parts (device_id/date): lists MP4 files

        Args:
            item: MediaSourceItem with identifier indicating browse depth.

        Returns:
            BrowseMediaSource with children at the appropriate level.
        """
        base_path = Path(
            self.hass.config.path("media", RECORDING_STORAGE_SUBDIR)
        )

        if not item.identifier:
            # Root level: list all device_id directories
            return await self._async_browse_root(base_path)

        parts = item.identifier.split("/")

        if len(parts) == 1:
            # Device level: list date subdirectories
            return await self._async_browse_device(base_path, parts[0])

        if len(parts) == 2:
            # Date level: list MP4 files
            return await self._async_browse_date(
                base_path, parts[0], parts[1]
            )

        # Invalid depth -- return empty
        return self._make_directory(
            identifier=item.identifier,
            title="Unknown",
            children=[],
        )

    async def _async_browse_root(
        self, base_path: Path
    ) -> BrowseMediaSource:
        """List device directories at root level."""

        def _list_devices() -> list[str]:
            if not base_path.is_dir():
                return []
            return sorted(
                [d.name for d in base_path.iterdir() if d.is_dir()],
                reverse=True,
            )

        devices = await self.hass.async_add_executor_job(_list_devices)

        children = [
            self._make_directory(
                identifier=device_id,
                title=f"Camera {device_id}",
            )
            for device_id in devices
        ]

        return self._make_directory(
            identifier="",
            title=self.name,
            children=children,
        )

    async def _async_browse_device(
        self, base_path: Path, device_id: str
    ) -> BrowseMediaSource:
        """List date directories for a specific device."""
        device_path = base_path / device_id

        def _list_dates() -> list[str]:
            if not device_path.is_dir():
                return []
            return sorted(
                [d.name for d in device_path.iterdir() if d.is_dir()],
                reverse=True,
            )

        dates = await self.hass.async_add_executor_job(_list_dates)

        children = [
            self._make_directory(
                identifier=f"{device_id}/{date_str}",
                title=date_str,
            )
            for date_str in dates
        ]

        return self._make_directory(
            identifier=device_id,
            title=f"Camera {device_id}",
            children=children,
        )

    async def _async_browse_date(
        self, base_path: Path, device_id: str, date_str: str
    ) -> BrowseMediaSource:
        """List MP4 files for a specific device and date."""
        date_path = base_path / device_id / date_str

        def _list_files() -> list[str]:
            if not date_path.is_dir():
                return []
            return sorted(
                [f.name for f in date_path.iterdir() if f.suffix == ".mp4"],
                reverse=True,
            )

        files = await self.hass.async_add_executor_job(_list_files)

        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{device_id}/{date_str}/{filename}",
                media_class=MediaClass.VIDEO,
                media_content_type=MediaType.VIDEO,
                title=self._format_filename_title(filename),
                can_play=True,
                can_expand=False,
            )
            for filename in files
        ]

        return self._make_directory(
            identifier=f"{device_id}/{date_str}",
            title=date_str,
            children=children,
        )

    @staticmethod
    def _format_filename_title(filename: str) -> str:
        """Extract a human-readable timestamp from a recording filename.

        Filenames follow the pattern: {device_id}_{YYYYMMDD}_{HHMMSS}.mp4
        Returns the time portion formatted as "HH:MM:SS".
        """
        name = filename.removesuffix(".mp4")
        parts = name.rsplit("_", maxsplit=1)
        if len(parts) == 2 and len(parts[1]) == 6:
            time_str = parts[1]
            try:
                return f"{time_str[0:2]}:{time_str[2:4]}:{time_str[4:6]}"
            except (IndexError, ValueError):
                pass
        return filename

    @staticmethod
    def _make_directory(
        identifier: str,
        title: str,
        children: list[BrowseMediaSource] | None = None,
    ) -> BrowseMediaSource:
        """Create a BrowseMediaSource directory node."""
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=title,
            can_play=False,
            can_expand=True,
            children=children or [],
        )
