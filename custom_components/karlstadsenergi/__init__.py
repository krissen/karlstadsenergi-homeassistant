"""The Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

try:
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_TYPE_NONE = StatisticMeanType.NONE
except ImportError:
    _MEAN_TYPE_NONE = None  # type: ignore[assignment]

try:
    from homeassistant.util.unit_conversion import EnergyConverter

    _ENERGY_UNIT_CLASS: str | None = EnergyConverter.UNIT_CLASS
except ImportError:
    _ENERGY_UNIT_CLASS = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    FEE_SENSORS,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    PLATFORMS,
    SKIP_GROUP_NAMES,
    URL_SPOT_PRICES,
)

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = timedelta(minutes=5)


@dataclass
class KarlstadsenergiData:
    """Runtime data for a Karlstadsenergi config entry."""

    api: KarlstadsenergiApi
    waste_coordinator: KarlstadsenergiWasteCoordinator
    consumption_coordinator: KarlstadsenergiConsumptionCoordinator
    contract_coordinator: KarlstadsenergiContractCoordinator
    spot_price_coordinator: KarlstadsenergiSpotPriceCoordinator
    setup_options: dict


type KarlstadsenergiConfigEntry = ConfigEntry[KarlstadsenergiData]


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
        """Persist current session cookies to config entry.

        Only saves when both required cookies are present, preventing
        invalid/partial cookies from being persisted after auth failures.
        """
        cookies = self.api.get_session_cookies()
        if (
            cookies
            and "ASP.NET_SessionId" in cookies
            and ".PORTALAUTH" in cookies
            and cookies != self._entry.data.get("session_cookies")
        ):
            new_data = {**self._entry.data, "session_cookies": cookies}
            self.hass.config_entries.async_update_entry(
                self._entry,
                data=new_data,
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
        """Fetch waste collection data."""
        try:
            # Primary: detailed services (requires flex page visit)
            services = []
            dates = {}
            try:
                all_services = await self.api.async_get_flex_services()
                services = [
                    s
                    for s in all_services
                    if s.get("FSStatusName") == "Aktiv"
                    and s.get("FlexServiceGroupName") not in SKIP_GROUP_NAMES
                ]
                if services:
                    service_ids = [
                        s["FlexServiceId"] for s in services if "FlexServiceId" in s
                    ]
                    dates = await self.api.async_get_flex_dates(service_ids)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.info(
                    "Detailed flex services unavailable, using summary fallback"
                )
                _LOGGER.debug("Flex service error details", exc_info=True)

            # Fallback: simple summary from start page
            next_dates = []
            if not services:
                next_dates = await self.api.async_get_next_flex_dates()

            return {
                "services": services,
                "dates": dates,
                "next_dates": next_dates,
            }

        except KarlstadsenergiAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        finally:
            self._save_cookies()


class KarlstadsenergiConsumptionCoordinator(_CookieSavingCoordinator):
    """Coordinator for electricity consumption data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
        customer_id: str = "",
    ) -> None:
        super().__init__(
            hass, api, update_interval_hours, entry, f"{DOMAIN}_consumption"
        )
        self._customer_id = customer_id
        self._statistic_id = f"{DOMAIN}:electricity_consumption_{customer_id}"

    async def _async_update_data(self) -> dict:
        """Fetch electricity consumption data."""
        try:
            consumption = await self.api.async_get_consumption()

            # Get hourly data using the model from the default response
            hourly = {}
            model = consumption.get("ConsumptionModel")
            if model:
                try:
                    hourly = await self.api.async_get_hourly_consumption(model)
                except Exception:
                    _LOGGER.debug("Hourly consumption unavailable")

            service_info = {}
            try:
                service_info = await self.api.async_get_service_info()
            except Exception:
                _LOGGER.debug("GetServiceInfo failed, continuing without it")

            fee_data = {}
            if model:
                try:
                    fee_data = await self.api.async_get_fee_consumption(model)
                except Exception:
                    _LOGGER.debug("Fee consumption unavailable")

            # Import hourly data into long-term statistics
            if hourly and self._customer_id:
                try:
                    await self._async_import_statistics(hourly)
                except Exception:
                    _LOGGER.debug("Statistics import failed", exc_info=True)

            # Import monthly fee data into long-term statistics
            if fee_data and self._customer_id:
                try:
                    await self._async_import_fee_statistics(fee_data)
                except Exception:
                    _LOGGER.debug("Fee statistics import failed", exc_info=True)

            return {
                "consumption": consumption,
                "hourly": hourly,
                "service_info": service_info,
                "fee_data": fee_data,
            }
        except KarlstadsenergiAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        finally:
            self._save_cookies()

    @staticmethod
    def _parse_aspnet_date(date_str: str) -> datetime | None:
        """Parse ASP.NET date format '/Date(EPOCH_MS)/' to UTC datetime."""
        match = re.search(r"/Date\((\d+)\)/", date_str)
        if not match:
            return None
        epoch_ms = int(match.group(1))
        return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)

    async def _async_import_statistics(self, hourly_data: dict) -> None:
        """Import hourly consumption data into HA long-term statistics."""
        chart = hourly_data.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return
        data_points = series_list[0].get("data") or []
        if not data_points:
            return

        statistic_id = self._statistic_id
        meta_kwargs: dict = {
            "has_mean": False,
            "has_sum": True,
            "name": "Karlstadsenergi Electricity Consumption",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }
        if _MEAN_TYPE_NONE is not None:
            meta_kwargs["mean_type"] = _MEAN_TYPE_NONE
        if _ENERGY_UNIT_CLASS is not None:
            meta_kwargs["unit_class"] = _ENERGY_UNIT_CLASS
        metadata = StatisticMetaData(**meta_kwargs)

        # Check what's already been imported
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        if last_stats and statistic_id in last_stats:
            last_stat = last_stats[statistic_id][0]
            last_stats_time_dt = dt_util.utc_from_timestamp(last_stat["start"])
            _sum = last_stat.get("sum", 0.0) or 0.0
        else:
            last_stats_time_dt = None
            _sum = 0.0

        statistics: list[StatisticData] = []
        for point in data_points:
            value = point.get("y")
            if value is None:
                continue
            point_dt = self._parse_aspnet_date(point.get("date", ""))
            if point_dt is None:
                continue
            # Truncate to hour boundary
            point_dt = point_dt.replace(minute=0, second=0, microsecond=0)
            # Skip already-imported points
            if last_stats_time_dt is not None and point_dt <= last_stats_time_dt:
                continue
            _sum += float(value)
            statistics.append(
                StatisticData(
                    start=point_dt,
                    state=float(value),
                    sum=_sum,
                )
            )

        if statistics:
            async_add_external_statistics(self.hass, metadata, statistics)
            _LOGGER.debug(
                "Imported %d hourly statistics points (last: %s)",
                len(statistics),
                statistics[-1].get("start") if statistics else "none",
            )

    async def _async_import_fee_statistics(self, fee_data: dict) -> None:
        """Import monthly fee data into HA long-term statistics.

        Creates one statistic per fee type (consumption fee, power fee, etc.)
        with monthly granularity. Follows the Tibber pattern: unit_class is
        omitted for monetary values since currencies don't convert.
        """
        chart = fee_data.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return

        for series in series_list:
            series_id = series.get("id", "")
            if series_id not in FEE_SENSORS:
                continue

            fee_info = FEE_SENSORS[series_id]
            statistic_id = f"{DOMAIN}:cost_{fee_info.stat_suffix}_{self._customer_id}"
            data_points = series.get("data") or []
            if not data_points:
                continue

            meta_kwargs: dict = {
                "has_mean": False,
                "has_sum": True,
                "name": f"Karlstadsenergi {fee_info.name}",
                "source": DOMAIN,
                "statistic_id": statistic_id,
                "unit_of_measurement": "SEK",
                "unit_class": None,
            }
            if _MEAN_TYPE_NONE is not None:
                meta_kwargs["mean_type"] = _MEAN_TYPE_NONE
            metadata = StatisticMetaData(**meta_kwargs)

            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
            )

            if last_stats and statistic_id in last_stats:
                last_stat = last_stats[statistic_id][0]
                last_stats_time_dt = dt_util.utc_from_timestamp(last_stat["start"])
                _sum = last_stat.get("sum", 0.0) or 0.0
            else:
                last_stats_time_dt = None
                _sum = 0.0

            statistics: list[StatisticData] = []
            sorted_points = sorted(data_points, key=lambda p: p.get("dateInterval", ""))
            for point in sorted_points:
                value = point.get("y")
                if value is None:
                    continue
                date_str = point.get("dateInterval", "")
                if not date_str:
                    continue
                try:
                    point_dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, TypeError):
                    continue
                if last_stats_time_dt is not None and point_dt <= last_stats_time_dt:
                    continue
                _sum += float(value)
                statistics.append(
                    StatisticData(
                        start=point_dt,
                        state=float(value),
                        sum=_sum,
                    )
                )

            if statistics:
                async_add_external_statistics(self.hass, metadata, statistics)
                _LOGGER.debug(
                    "Imported %d fee statistics points for %s",
                    len(statistics),
                    series_id,
                )


class KarlstadsenergiContractCoordinator(_CookieSavingCoordinator):
    """Coordinator for contract details (daily refresh)."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        entry: ConfigEntry,
        site_ids: list[str],
    ) -> None:
        super().__init__(hass, api, 24, entry, f"{DOMAIN}_contracts")
        self._site_ids = site_ids

    async def _async_update_data(self) -> dict:
        """Fetch contract details."""
        try:
            contracts = await self.api.async_get_contract_details(self._site_ids)
            return {"contracts": contracts}
        except KarlstadsenergiAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        finally:
            self._save_cookies()


class KarlstadsenergiSpotPriceCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator for Evado public spot prices (15-minute refresh)."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_spot_price",
            update_interval=timedelta(minutes=15),
        )

    async def _async_update_data(self) -> dict:
        """Fetch spot prices from Evado public API."""
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(15):
                resp = await session.get(URL_SPOT_PRICES)
                resp.raise_for_status()
                data = await resp.json()
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Spot price fetch timed out: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Spot price HTTP error: {err}") from err
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            raise UpdateFailed(f"Spot price parse error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Spot price fetch failed: {err}") from err
        return self._parse_spot_data(data)

    @staticmethod
    def _parse_spot_data(data: dict) -> dict:
        """Parse Evado spot price response.

        Response format:
        {"timezone": "Europe/Stockholm", "spotprices": [
            {"Spotprice": {"region": "SE3", "start_time": "...", "end_time": "...",
                           "price": 52.235, "modified": "..."}}, ...
        ]}

        Prices are in öre/kWh, 15-minute intervals, times in UTC.
        """
        spotprices = data.get("spotprices") or []
        if not spotprices:
            return {
                "current_price": None,
                "prices": [],
                "region": "SE3",
                "stale": False,
            }

        # Parse all price points
        prices = []
        for entry in spotprices:
            sp = entry.get("Spotprice") or {}
            start_str = sp.get("start_time", "")
            price_ore = sp.get("price")
            if not start_str or price_ore is None:
                continue
            # Parse UTC time: "2026-03-26T23:00:00+0000"
            try:
                start_dt = datetime.fromisoformat(start_str.replace("+0000", "+00:00"))
            except (ValueError, TypeError):
                continue
            prices.append(
                {
                    "start": start_dt,
                    "price_ore": float(price_ore),
                    "price_sek": round(float(price_ore) / 100, 4),
                }
            )

        prices.sort(key=lambda p: p["start"])

        # Find current price (fall back to most recent known price if stale)
        now = datetime.now(tz=timezone.utc) if prices else None
        current_price = None
        stale = False
        if now and prices:
            for i, p in enumerate(prices):
                next_start = prices[i + 1]["start"] if i + 1 < len(prices) else None
                if next_start is None or now < next_start:
                    if now >= p["start"]:
                        current_price = p["price_sek"]
                    break
            # If stale (now is past all known prices), use the last known price.
            # A price is considered stale when now has gone past the last bucket's
            # nominal 15-minute window (last_start + 15 min), meaning we no longer
            # have fresh data but are reusing the most recent known value.
            if current_price is None and now >= prices[-1]["start"]:
                current_price = prices[-1]["price_sek"]
            if current_price is not None:
                last_bucket_end = prices[-1]["start"] + timedelta(minutes=15)
                stale = now >= last_bucket_end

        return {
            "current_price": current_price,
            "prices": prices,
            "region": "SE3",
            "stale": stale,
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: KarlstadsenergiConfigEntry
) -> bool:
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

    api = KarlstadsenergiApi(personnummer, auth_method, password)
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
        hass,
        api,
        update_interval,
        entry,
    )
    customer_id = entry.data.get("customer_code") or personnummer
    consumption_coordinator = KarlstadsenergiConsumptionCoordinator(
        hass,
        api,
        max(update_interval // 6, 1),
        entry,
        customer_id=customer_id,
    )

    try:
        await waste_coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await api.async_close()
        raise
    except Exception as err:
        await api.async_close()
        raise ConfigEntryNotReady(f"Could not fetch waste data: {err}") from err

    try:
        await consumption_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # Review note (V2): Consumption failure is logged here and the
        # integration continues without consumption/contract data. This
        # is intentional -- waste collection (the primary feature) should
        # work even if the electricity API is temporarily unavailable.
        _LOGGER.warning("Could not fetch consumption data: %s", err)

    # Extract site_id from consumption data for contract fetching
    site_ids: list[str] = []
    if consumption_coordinator.data:
        consumption = consumption_coordinator.data.get("consumption") or {}
        model = consumption.get("ConsumptionModel") or {}
        site_id = model.get("SiteId", "")
        if site_id:
            site_ids = [str(site_id)]

    # Contract coordinator (24h interval, needs site_id from consumption)
    contract_coordinator = KarlstadsenergiContractCoordinator(
        hass,
        api,
        entry,
        site_ids,
    )
    try:
        await contract_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning("Could not fetch contract data: %s", err)

    # Spot price coordinator (15 min interval, public API, no auth).
    spot_price_coordinator = KarlstadsenergiSpotPriceCoordinator(hass)
    try:
        await spot_price_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning("Could not fetch spot prices: %s", err)

    entry.runtime_data = KarlstadsenergiData(
        api=api,
        waste_coordinator=waste_coordinator,
        consumption_coordinator=consumption_coordinator,
        contract_coordinator=contract_coordinator,
        spot_price_coordinator=spot_price_coordinator,
        setup_options=dict(entry.options),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Heartbeat: keep session alive every 5 minutes
    async def _heartbeat(_now=None) -> None:
        try:
            await api.async_heartbeat()
        except Exception:
            _LOGGER.debug("Heartbeat failed", exc_info=True)

    cancel_heartbeat = async_track_time_interval(
        hass,
        _heartbeat,
        HEARTBEAT_INTERVAL,
    )
    entry.async_on_unload(cancel_heartbeat)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: KarlstadsenergiConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        await entry.runtime_data.api.async_close()

    return unload_ok


async def _async_reload_entry(
    hass: HomeAssistant,
    entry: KarlstadsenergiConfigEntry,
) -> None:
    """Reload entry on options change (ignores data-only updates like cookie saves)."""
    if dict(entry.options) != entry.runtime_data.setup_options:
        await hass.config_entries.async_reload(entry.entry_id)
