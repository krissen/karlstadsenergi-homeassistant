"""Diagnostics support for Karlstadsenergi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import KarlstadsenergiConfigEntry
from .const import CONF_PERSONNUMMER

TO_REDACT_CONFIG = {
    CONF_PERSONNUMMER,
    CONF_PASSWORD,
    "session_cookies",
    "customer_id",
    "sub_user_id",
    "customer_code",
    "GsrnNumber",
    "title",
}

# Keys to redact from coordinator data payloads. These fields contain personally
# identifiable or sensitive infrastructure information (addresses, meter IDs,
# GSRN numbers) that must not appear in diagnostics exports.
TO_REDACT_DATA = {
    "FlexServicePlaceAddress",
    "SiteName",
    "GsrnNumber",
    "MeterNumber",
    "ServiceIdentifier",
    "NetAreaId",
    "NetAreaCode",
    "Address",
    "SiteId",
    "ContractCode",
    "ContractId",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: KarlstadsenergiConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT_CONFIG),
        "waste_data": async_redact_data(
            runtime.waste_coordinator.data or {}, TO_REDACT_DATA
        ),
        "consumption_data": async_redact_data(
            runtime.consumption_coordinator.data or {}, TO_REDACT_DATA
        ),
        "contract_data": async_redact_data(
            runtime.contract_coordinator.data or {}, TO_REDACT_DATA
        ),
        "spot_price_data": {
            "current_price": (runtime.spot_price_coordinator.data or {}).get(
                "current_price"
            ),
            "region": (runtime.spot_price_coordinator.data or {}).get("region"),
            "price_count": len(
                (runtime.spot_price_coordinator.data or {}).get("prices") or []
            ),
        },
    }
