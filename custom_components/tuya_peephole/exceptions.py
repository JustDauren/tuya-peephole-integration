"""Custom exceptions for the Tuya Peephole Camera integration."""

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady


class TuyaAuthError(ConfigEntryAuthFailed):
    """Raised when Tuya authentication fails (wrong credentials or expired session)."""


class TuyaApiError(ConfigEntryNotReady):
    """Raised when the Tuya API is unreachable or returns a non-auth error."""
