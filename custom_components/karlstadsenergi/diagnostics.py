"""Diagnostics support for Karlstadsenergi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_PERSONNUMMER, DOMAIN

TO_REDACT_CONFIG = {
    CONF_PERSONNUMMER,
    CONF_PASSWORD,
    "session_cookies",
    "customer_id",
    "sub_user_id",
    "customer_code",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    waste_coordinator = data["waste_coordinator"]
    consumption_coordinator = data["consumption_coordinator"]

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT_CONFIG),
        "waste_data": waste_coordinator.data,
        "consumption_data": consumption_coordinator.data,
    }
