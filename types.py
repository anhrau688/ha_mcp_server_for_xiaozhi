"""Types for the MCP server integration."""

from homeassistant.config_entries import ConfigEntry
from .session import SessionManager

#type WsMCPServerConfigEntry = ConfigEntry[SessionManager]


class WsMCPServerConfigEntry(ConfigEntry):
    """Config entry for the MCP server."""
    runtime_data: SessionManager
    