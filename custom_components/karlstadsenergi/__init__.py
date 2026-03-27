"""The Karlstadsenergi integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    KarlstadsenergiApi,
    KarlstadsenergiApiError,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from .const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
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


class _CookieSavingCoordinator(DataUpdateCoordinator[dict]):
    """Base coordinator that persists session cookies after each update."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
        name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(hours=update_interval_hours),
        )
        self.api = api
        self._entry = entry

    def _save_cookies(self) -> None:
        """Persist current session cookies to config entry."""
        cookies = self.api.get_session_cookies()
        if cookies and cookies != self._entry.data.get("session_cookies"):
            new_data = {**self._entry.data, "session_cookies": cookies}
            self.hass.config_entries.async_update_entry(
                self._entry, data=new_data,
            )


class KarlstadsenergiWasteCoordinator(_CookieSavingCoordinator):
    """Coordinator for waste collection data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(hass, api, update_interval_hours, entry, f"{DOMAIN}_waste")

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

            self._save_cookies()
            return {"services": active, "dates": dates}

        except KarlstadsenergiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err


class KarlstadsenergiConsumptionCoordinator(_CookieSavingCoordinator):
    """Coordinator for electricity consumption data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(hass, api, update_interval_hours, entry, f"{DOMAIN}_consumption")

    async def _async_update_data(self) -> dict:
        """Fetch electricity consumption data."""
        try:
            consumption = await self.api.async_get_consumption()
            service_info = await self.api.async_get_service_info()
            self._save_cookies()
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
    personnummer = entry.data[CONF_PERSONNUMMER]
    auth_method = entry.data.get(CONF_AUTH_METHOD, AUTH_BANKID)
    password = entry.data.get(CONF_PASSWORD, "")

    update_interval = min(
        max(
            entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            MIN_UPDATE_INTERVAL,
        ),
        MAX_UPDATE_INTERVAL,
    )

    # Try to reuse API instance from config flow (BankID session handoff)
    api = None
    hass.data.setdefault(DOMAIN, {})
    pending = hass.data[DOMAIN].pop("pending_api", None)
    if pending is not None and pending._authenticated:
        api = pending
        _LOGGER.debug("Reusing authenticated API session from config flow")

    if api is None:
        api = KarlstadsenergiApi(personnummer, auth_method, password)
        # Restore session cookies if available
        saved_cookies = entry.data.get("session_cookies")
        if saved_cookies:
            api.set_session_cookies(saved_cookies)
        elif auth_method == AUTH_PASSWORD:
            try:
                await api.authenticate()
            except KarlstadsenergiApiError as err:
                await api.async_close()
                raise ConfigEntryNotReady(f"Could not authenticate: {err}") from err

    waste_coordinator = KarlstadsenergiWasteCoordinator(
        hass, api, update_interval, entry,
    )
    consumption_coordinator = KarlstadsenergiConsumptionCoordinator(
        hass, api, max(update_interval // 6, 1), entry,
    )

    try:
        await waste_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await api.async_close()
        raise ConfigEntryNotReady(f"Could not fetch waste data: {err}") from err

    try:
        await consumption_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning("Could not fetch consumption data: %s", err)

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
