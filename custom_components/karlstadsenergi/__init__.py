"""The Karlstadsenergi integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    KarlstadsenergiApi,
    KarlstadsenergiApiError,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from .const import (
    CONF_CUSTOMER_NUMBER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    PLATFORMS,
    SKIP_GROUP_NAMES,
)

_LOGGER = logging.getLogger(__name__)

type KarlstadsenergiConfigEntry = ConfigEntry


class KarlstadsenergiWasteCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator for waste collection data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_waste",
            update_interval=timedelta(hours=update_interval_hours),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        """Fetch waste collection services and pickup dates."""
        try:
            services = await self.api.async_get_flex_services()

            # Filter to active container services (skip billing-only)
            active = [
                s for s in services
                if s.get("FSStatusName") == "Aktiv"
                and s.get("FlexServiceGroupName") not in SKIP_GROUP_NAMES
            ]

            # Get next pickup dates
            service_ids = [s["FlexServiceId"] for s in active]
            dates = await self.api.async_get_flex_dates(service_ids)

            return {"services": active, "dates": dates}

        except KarlstadsenergiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err


class KarlstadsenergiConsumptionCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator for electricity consumption data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_consumption",
            update_interval=timedelta(hours=update_interval_hours),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        """Fetch electricity consumption data."""
        try:
            consumption = await self.api.async_get_consumption()
            service_info = await self.api.async_get_service_info()
            return {
                "consumption": consumption,
                "service_info": service_info,
            }
        except KarlstadsenergiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Karlstadsenergi from a config entry."""
    customer_number = entry.data[CONF_CUSTOMER_NUMBER]
    password = entry.data[CONF_PASSWORD]

    update_interval = min(
        max(
            entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            MIN_UPDATE_INTERVAL,
        ),
        MAX_UPDATE_INTERVAL,
    )

    api = KarlstadsenergiApi(customer_number, password)

    try:
        await api.authenticate()
    except KarlstadsenergiApiError as err:
        await api.async_close()
        raise ConfigEntryNotReady(f"Could not authenticate: {err}") from err

    waste_coordinator = KarlstadsenergiWasteCoordinator(
        hass, api, update_interval,
    )
    consumption_coordinator = KarlstadsenergiConsumptionCoordinator(
        hass, api, max(update_interval // 6, 1),
    )

    await waste_coordinator.async_config_entry_first_refresh()
    await consumption_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "waste_coordinator": waste_coordinator,
        "consumption_coordinator": consumption_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        entry.add_update_listener(_async_reload_entry)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS,
    )
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["api"].async_close()
    return unload_ok


async def _async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry,
) -> None:
    """Reload entry on options change."""
    await hass.config_entries.async_reload(entry.entry_id)
