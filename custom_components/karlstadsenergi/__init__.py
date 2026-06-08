"""The Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

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
from homeassistant.helpers.storage import Store
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
    CONF_HISTORY_YEARS,
    CONF_PERSONNUMMER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HISTORY_YEARS,
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

# Local cache of each coordinator's last-known data, so entities keep their
# values across a restart/reload instead of going unavailable until the next
# successful fetch (essential for BankID, whose session dies every ~15 min).
CACHE_STORAGE_VERSION = 1
CACHE_SAVE_DELAY = 30  # seconds -- debounce frequent coordinator successes
# Heavy hourly time-series are dropped from the cache: they dominate the size
# (~10 MB of 2-year hourly data), drive only secondary attributes / DH detail
# sensors, and are recoverable -- long-term statistics persist in the recorder
# and the series repopulate on the first successful fetch after a restart. The
# values that matter (pickup dates, consumption total, cost, contracts, spot)
# live in the small keys we keep.
CACHE_PRUNE_KEYS = ("hourly", "flow", "dt")


def _json_encode(obj: Any) -> Any:
    """Recursively make coordinator data JSON-serializable.

    Only datetimes need transforming (spot price ``prices[*]["start"]`` and the
    per-coordinator ``last_success_time``); everything else in the cached data
    is already JSON-safe (waste/consumption/contract dates are stored as
    strings). ``datetime`` is checked before ``date`` since it subclasses it.
    """
    if isinstance(obj, datetime):
        return {"__dt__": obj.isoformat()}
    if isinstance(obj, date):
        return {"__date__": obj.isoformat()}
    if isinstance(obj, dict):
        return {k: _json_encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_encode(v) for v in obj]
    return obj


def _json_decode(obj: Any) -> Any:
    """Reverse of :func:`_json_encode` -- restore datetimes from their markers."""
    if isinstance(obj, dict):
        if len(obj) == 1 and "__dt__" in obj:
            return datetime.fromisoformat(obj["__dt__"])
        if len(obj) == 1 and "__date__" in obj:
            return date.fromisoformat(obj["__date__"])
        return {k: _json_decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_decode(v) for v in obj]
    return obj


class _DataCache:
    """Per-entry on-disk cache of coordinator data (HA Store, debounced)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._store: Store = Store(
            hass, CACHE_STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.cache"
        )
        # name -> {"data": <coordinator.data>, "last_success_time": datetime}
        self._state: dict[str, dict] = {}

    async def async_load(self) -> dict:
        """Load + decode the cache; returns the live state dict (also kept)."""
        raw = await self._store.async_load()
        decoded = _json_decode(raw) if raw else {}
        self._state = decoded if isinstance(decoded, dict) else {}
        return self._state

    def record(self, name: str, data: dict, last_success_time: datetime) -> None:
        """Update one coordinator's slice and schedule a debounced save.

        Heavy time-series keys are dropped (shallow copy -- the live
        ``coordinator.data`` the entities use is never mutated).
        """
        if isinstance(data, dict):
            cached = {k: v for k, v in data.items() if k not in CACHE_PRUNE_KEYS}
        else:
            cached = data
        self._state[name] = {"data": cached, "last_success_time": last_success_time}
        self._store.async_delay_save(
            lambda: _json_encode(self._state), CACHE_SAVE_DELAY
        )

    async def async_remove(self) -> None:
        """Delete the cache file (entry removed)."""
        await self._store.async_remove()


@dataclass
class KarlstadsenergiData:
    """Runtime data for a Karlstadsenergi config entry."""

    api: KarlstadsenergiApi
    waste_coordinator: KarlstadsenergiWasteCoordinator
    consumption_coordinator: KarlstadsenergiConsumptionCoordinator
    district_heating_coordinator: KarlstadsenergiDistrictHeatingCoordinator
    contract_coordinator: KarlstadsenergiContractCoordinator
    spot_price_coordinator: KarlstadsenergiSpotPriceCoordinator
    setup_options: dict


type KarlstadsenergiConfigEntry = ConfigEntry[KarlstadsenergiData]


def _cookie_fingerprint(cookies: dict[str, str] | None) -> dict[str, str]:
    """Non-reversible fingerprint of cookies for debug logging.

    Logs only ``<length>:<sha256 prefix>`` per key -- never the value -- so we
    can see *whether* ASP.NET_SessionId / .PORTALAUTH changed across a
    persist/restore cycle without leaking the secrets.
    """
    import hashlib

    if not cookies:
        return {}
    return {
        k: f"{len(v)}:{hashlib.sha256(v.encode()).hexdigest()[:8]}"
        for k, v in sorted(cookies.items())
    }


def _persist_session_cookies(
    hass: HomeAssistant, entry: ConfigEntry, api: KarlstadsenergiApi
) -> None:
    """Persist the API's current session cookies to the config entry.

    The portal reissues the ``.PORTALAUTH`` forms-auth ticket with a fresh
    value (and a fresh embedded expiry) on every request -- sliding
    expiration. The live in-memory session always holds the latest ticket,
    but the persisted copy goes stale unless refreshed regularly, INCLUDING
    after heartbeats. If it goes stale, a Home Assistant restart loads an
    expired ticket and setup fails to authenticate -- fatal for BankID, which
    cannot re-auth non-interactively. Only persists when both required cookies
    are present (never a partial/failed-auth state) and the value changed.
    """
    cookies = api.get_session_cookies()
    if (
        cookies
        and "ASP.NET_SessionId" in cookies
        and ".PORTALAUTH" in cookies
        and cookies != entry.data.get("session_cookies")
    ):
        old = entry.data.get("session_cookies")
        _LOGGER.debug(
            "Persisting session cookies: old=%s new=%s",
            _cookie_fingerprint(old),
            _cookie_fingerprint(cookies),
        )
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "session_cookies": cookies}
        )


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
            config_entry=entry,
            name=name,
            update_interval=timedelta(hours=update_interval_hours),
        )
        self.api = api
        self._entry = entry
        # Timestamp of the last successful update; exposed via entities as
        # `last_updated` so retained (stale) values show when they were fetched.
        self.last_success_time: datetime | None = None
        # Set by setup to persist each success to the on-disk cache.
        self.on_success_callback: Callable[[str, dict, datetime], None] | None = None

    def _save_cookies(self) -> None:
        """Persist current session cookies to the config entry."""
        _persist_session_cookies(self.hass, self._entry, self.api)

    async def _async_update_data(self) -> dict:
        """Fetch via the subclass, stamping the time on success.

        Subclasses implement ``_fetch_data``. A failed fetch propagates without
        updating ``last_success_time`` (and the coordinator keeps its previous
        ``data``, so entities retain their last values).
        """
        data = await self._fetch_data()
        self.last_success_time = dt_util.utcnow()
        if self.on_success_callback is not None:
            self.on_success_callback(self.name, data, self.last_success_time)
        return data

    async def _fetch_data(self) -> dict:
        """Fetch fresh data. Implemented by subclasses."""
        raise NotImplementedError


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

    async def _fetch_data(self) -> dict:
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


# ── Shared utility consumption coordinator ──────────────────────


class _UtilityConsumptionCoordinator(_CookieSavingCoordinator):
    """Base coordinator for utility consumption data.

    Shared by electricity and district heating coordinators. Provides
    date widening, ASP.NET date parsing, and long-term statistics import.
    Subclasses implement ``_async_update_data`` with utility-specific logic.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
        *,
        utility_label: str,
        customer_id: str,
        history_years: int,
        stat_name: str,
        stat_prefix: str,
        fee_stat_prefix: str,
    ) -> None:
        super().__init__(
            hass, api, update_interval_hours, entry, f"{DOMAIN}_{utility_label}"
        )
        self._utility_label = utility_label
        self._customer_id = customer_id
        self._history_years = history_years
        self._stat_name = stat_name
        self._statistic_id = f"{DOMAIN}:{stat_prefix}_{customer_id}"
        self._fee_stat_prefix = fee_stat_prefix
        self._backfill_done = False

    @staticmethod
    def _widen_start_date(model: dict, history_years: int) -> dict:
        """Return a copy of the model with StartDate moved back.

        Uses ContractsStartDate as the lower bound (earliest available
        data). If the calculated date is earlier than ContractsStartDate,
        ContractsStartDate wins.
        """
        widened = {**model}
        now = datetime.now(tz=timezone.utc)
        target = datetime(
            year=now.year - history_years, month=1, day=1, tzinfo=timezone.utc
        )
        target_ms = int(target.timestamp() * 1000)

        # Parse ContractsStartDate as lower bound
        contracts_start = model.get("ContractsStartDate", "")
        match = re.search(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", contracts_start)
        if match:
            contracts_ms = int(match.group(1))
            target_ms = max(target_ms, contracts_ms)

        widened["StartDate"] = f"/Date({target_ms})/"
        return widened

    @staticmethod
    def _parse_aspnet_date(date_str: str) -> datetime | None:
        """Parse ASP.NET date format '/Date(EPOCH_MS)/' to UTC datetime."""
        match = re.search(r"/Date\((\d+)(?:[+-]\d{4})?\)/", date_str)
        if not match:
            return None
        epoch_ms = int(match.group(1))
        return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)

    async def _async_import_consumption_statistics(self, hourly_data: dict) -> None:
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
            "name": f"Karlstadsenergi {self._stat_name}",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }
        if _MEAN_TYPE_NONE is not None:
            meta_kwargs["mean_type"] = _MEAN_TYPE_NONE
        if _ENERGY_UNIT_CLASS is not None:
            meta_kwargs["unit_class"] = _ENERGY_UNIT_CLASS
        metadata = StatisticMetaData(**meta_kwargs)

        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        if last_stats and statistic_id in last_stats:
            last_stat = last_stats[statistic_id][0]
            last_stats_time_dt = dt_util.utc_from_timestamp(last_stat["start"])
            _sum = last_stat.get("sum", 0.0) or 0.0
            _LOGGER.debug(
                "Resuming statistics for %s from %s (sum=%.1f)",
                statistic_id,
                last_stats_time_dt,
                _sum,
            )
        else:
            last_stats_time_dt = None
            _sum = 0.0
            _LOGGER.debug(
                "No existing statistics for %s, starting fresh import",
                statistic_id,
            )

        statistics: list[StatisticData] = []
        skipped = 0
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
                skipped += 1
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
                "Imported %d hourly statistics points (skipped %d, last: %s)",
                len(statistics),
                skipped,
                statistics[-1].get("start") if statistics else "none",
            )
        else:
            _LOGGER.debug(
                "No new hourly statistics to import (%d data points, %d skipped)",
                len(data_points),
                skipped,
            )

    async def _async_import_fee_statistics(self, fee_data: dict) -> None:
        """Import monthly fee data into HA long-term statistics.

        Creates one statistic per fee type (consumption fee, power fee, etc.)
        with monthly granularity. unit_class is explicitly set to None as
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
            statistic_id = (
                f"{DOMAIN}:{self._fee_stat_prefix}"
                f"_{fee_info.stat_suffix}_{self._customer_id}"
            )
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


# ── Electricity coordinator ─────────────────────────────────────


class KarlstadsenergiConsumptionCoordinator(_UtilityConsumptionCoordinator):
    """Coordinator for electricity consumption data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
        customer_id: str = "",
        history_years: int = DEFAULT_HISTORY_YEARS,
    ) -> None:
        super().__init__(
            hass,
            api,
            update_interval_hours,
            entry,
            utility_label="consumption",
            customer_id=customer_id,
            history_years=history_years,
            stat_name="Electricity Consumption",
            stat_prefix="electricity_consumption",
            fee_stat_prefix="cost",
        )

    async def _fetch_data(self) -> dict:
        """Fetch electricity consumption data."""
        try:
            consumption = await self.api.async_get_consumption()

            # Hourly data: use widened date range for initial backfill, then
            # narrow (~2 month) window to reduce payload (19k vs 1.4k rows).
            # Fee data + monthly consumption: always use wide range so that
            # the electricity price sensor can compute fee/kWh from
            # overlapping months. Monthly consumption is a lightweight
            # alternative to hourly (~26 rows) and doesn't require the
            # user to have ordered hourly metering.
            hourly = {}
            fee_data = {}
            monthly_kwh = {}
            model = consumption.get("ConsumptionModel")
            if model:
                wide_model = self._widen_start_date(model, self._history_years)
                fetch_model = wide_model if not self._backfill_done else model
                try:
                    hourly = await self.api.async_get_hourly_consumption(fetch_model)
                except KarlstadsenergiAuthError:
                    raise
                except Exception:
                    _LOGGER.debug("Hourly consumption unavailable")
                try:
                    fee_data = await self.api.async_get_fee_consumption(wide_model)
                except KarlstadsenergiAuthError:
                    raise
                except Exception:
                    _LOGGER.debug("Fee consumption unavailable")
                try:
                    monthly_kwh = await self.api.async_get_monthly_consumption(
                        wide_model
                    )
                except KarlstadsenergiAuthError:
                    raise
                except Exception:
                    _LOGGER.debug("Monthly consumption unavailable")

            # Import hourly data into long-term statistics
            if hourly and self._customer_id:
                try:
                    await self._async_import_consumption_statistics(hourly)
                except Exception:
                    _LOGGER.warning("Statistics import failed", exc_info=True)
            elif not hourly:
                _LOGGER.debug("No hourly data to import (empty response)")
            elif not self._customer_id:
                _LOGGER.warning("No customer_id set, skipping statistics import")

            # Import monthly fee data into long-term statistics
            if fee_data and self._customer_id:
                try:
                    await self._async_import_fee_statistics(fee_data)
                except Exception:
                    _LOGGER.warning("Fee statistics import failed", exc_info=True)
            elif not fee_data:
                _LOGGER.debug("No fee data to import (empty response)")

            if not self._backfill_done and (hourly or fee_data):
                self._backfill_done = True

            return {
                "consumption": consumption,
                "hourly": hourly,
                "fee_data": fee_data,
                "monthly_kwh": monthly_kwh,
            }
        except KarlstadsenergiAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        finally:
            self._save_cookies()


# ── District heating coordinator ────────────────────────────────


class KarlstadsenergiDistrictHeatingCoordinator(_UtilityConsumptionCoordinator):
    """Coordinator for district heating (fjärrvärme) consumption data.

    Uses the same GetConsumption endpoint as electricity but with
    UtilityId "F" instead of "E". Reads the base consumption model
    from the electricity coordinator to avoid duplicate API calls.
    """

    UTILITY_ID = "F"

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarlstadsenergiApi,
        update_interval_hours: int,
        entry: ConfigEntry,
        electricity_coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_id: str = "",
        history_years: int = DEFAULT_HISTORY_YEARS,
    ) -> None:
        super().__init__(
            hass,
            api,
            update_interval_hours,
            entry,
            utility_label="district_heating",
            customer_id=customer_id,
            history_years=history_years,
            stat_name="District Heating Consumption",
            stat_prefix="district_heating_consumption",
            fee_stat_prefix="dh_cost",
        )
        self._electricity_coordinator = electricity_coordinator

    @classmethod
    def _has_district_heating(cls, model: dict) -> bool:
        """Check if the consumption model includes district heating."""
        node = model.get("SelectedSiteGroupNode") or {}
        for utility in node.get("Utilities") or []:
            if utility.get("UtilityId") == cls.UTILITY_ID:
                return True
        return False

    def _prepare_dh_model(self, model: dict, history_years: int = 0) -> dict:
        """Return a copy of the consumption model configured for DH."""
        dh = {**model}
        dh["UtilityId"] = self.UTILITY_ID
        dh["IsUtilityChange"] = True
        dh["IsPageLoad"] = False
        if history_years > 0:
            dh = self._widen_start_date(dh, history_years)
        return dh

    def _get_base_model(self) -> dict | None:
        """Read the base consumption model from the electricity coordinator."""
        el_data = self._electricity_coordinator.data
        if not el_data:
            return None
        consumption = el_data.get("consumption") or {}
        return consumption.get("ConsumptionModel")

    async def _fetch_data(self) -> dict:
        """Fetch district heating consumption data."""
        try:
            model = self._get_base_model()
            if not model:
                _LOGGER.debug("No ConsumptionModel available for DH")
                return {"available": False}

            if not getattr(self, "_logged_utilities", False):
                node = model.get("SelectedSiteGroupNode") or {}
                utility_ids = [
                    u.get("UtilityId", "?") for u in node.get("Utilities") or []
                ]
                _LOGGER.info("Account utilities: %s", ", ".join(utility_ids) or "none")
                self._logged_utilities = True

            if not self._has_district_heating(model):
                return {"available": False}

            # Fetch daily DH consumption (includes CompareModel for sensor)
            dh_daily_model = self._prepare_dh_model(model)
            dh_consumption = await self.api.async_get_consumption_with_model(
                dh_daily_model
            )

            # Prepare DH models for historical data
            wide_dh_model = self._prepare_dh_model(model, self._history_years)
            fetch_model = wide_dh_model if not self._backfill_done else dh_daily_model

            # Fetch hourly DH consumption (for statistics import)
            dh_hourly = {}
            try:
                dh_hourly = await self.api.async_get_hourly_consumption(fetch_model)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.debug("DH hourly consumption unavailable")

            # Fetch monthly DH consumption
            dh_monthly = {}
            try:
                dh_monthly = await self.api.async_get_monthly_consumption(wide_dh_model)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.debug("DH monthly consumption unavailable")

            # Fetch DH fee/cost breakdown (SEK by month)
            dh_fee = {}
            try:
                dh_fee = await self.api.async_get_fee_consumption(wide_dh_model)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.debug("DH fee consumption unavailable")

            # Fetch DH flow data (m³)
            dh_flow = {}
            try:
                flow_model = self._prepare_dh_model(model)
                flow_model["Loadoptions"] = ["Flow"]
                dh_flow = await self.api.async_get_consumption_with_model(flow_model)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.debug("DH flow data unavailable")

            # Fetch DH temperature difference (dT)
            dh_dt = {}
            try:
                dt_model = self._prepare_dh_model(model)
                dt_model["Loadoptions"] = ["DT"]
                dh_dt = await self.api.async_get_consumption_with_model(dt_model)
            except KarlstadsenergiAuthError:
                raise
            except Exception:
                _LOGGER.debug("DH dT data unavailable")

            # Import hourly DH data into long-term statistics
            if dh_hourly and self._customer_id:
                try:
                    await self._async_import_consumption_statistics(dh_hourly)
                except Exception:
                    _LOGGER.warning("DH statistics import failed", exc_info=True)

            # Import monthly DH fee data into long-term statistics
            if dh_fee and self._customer_id:
                try:
                    await self._async_import_fee_statistics(dh_fee)
                except Exception:
                    _LOGGER.warning("DH fee statistics import failed", exc_info=True)

            if not self._backfill_done and (dh_hourly or dh_fee):
                self._backfill_done = True

            return {
                "available": True,
                "consumption": dh_consumption,
                "hourly": dh_hourly,
                "monthly_kwh": dh_monthly,
                "fee_data": dh_fee,
                "flow": dh_flow,
                "dt": dh_dt,
            }
        except KarlstadsenergiAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except KarlstadsenergiApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        finally:
            self._save_cookies()


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

    async def _fetch_data(self) -> dict:
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

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_spot_price",
            update_interval=timedelta(minutes=15),
        )
        # Mirror the auth coordinators so the entity mixin and on-disk cache
        # treat spot price uniformly (see _CookieSavingCoordinator).
        self.last_success_time: datetime | None = None
        self.on_success_callback: Callable[[str, dict, datetime], None] | None = None

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
        result = self._parse_spot_data(data)
        self.last_success_time = dt_util.utcnow()
        if self.on_success_callback is not None:
            self.on_success_callback(self.name, result, self.last_success_time)
        return result

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
        _LOGGER.debug(
            "Setup restoring session cookies: %s",
            _cookie_fingerprint(saved_cookies),
        )
        api.set_session_cookies(saved_cookies)
    elif auth_method == AUTH_PASSWORD:
        try:
            await api.authenticate()
        except KarlstadsenergiAuthError as err:
            # Credentials are wrong (or the account is locked) -- surface a reauth
            # flow and stop retrying, rather than hammering the portal login on the
            # ConfigEntryNotReady schedule (which can trigger a lockout).
            await api.async_close()
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except KarlstadsenergiApiError as err:
            await api.async_close()
            raise ConfigEntryNotReady(f"Could not authenticate: {err}") from err

    # Local cache of last-known coordinator data. When present, we seed each
    # coordinator from it and use async_refresh() instead of
    # async_config_entry_first_refresh() so a dead session at startup does NOT
    # abort setup -- entities load with their last (stale) values. The reauth
    # prompt is NOT suppressed: async_refresh() auto-calls async_start_reauth()
    # on ConfigEntryAuthFailed (see homeassistant/helpers/update_coordinator.py),
    # and entities still report data_stale=True. With no cache (fresh install)
    # we keep the strict behaviour: a failed first fetch aborts/prompts reauth.
    cache = _DataCache(hass, entry)
    cached = await cache.async_load()
    has_cache = bool(cached)

    def _seed(coordinator: DataUpdateCoordinator) -> None:
        """Seed a coordinator from the cache and wire success persistence."""
        slice_ = cached.get(coordinator.name)
        if slice_ and slice_.get("data") is not None:
            coordinator.data = slice_["data"]
            coordinator.last_success_time = slice_.get("last_success_time")
        coordinator.on_success_callback = cache.record

    async def _refresh(
        coordinator: DataUpdateCoordinator, *, critical: bool = False
    ) -> None:
        """Seed then refresh, choosing the strategy based on cache presence."""
        _seed(coordinator)
        if has_cache:
            # Cached values are already showing; never abort setup.
            await coordinator.async_refresh()
            return
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            await api.async_close()
            raise
        except Exception as err:
            if critical:
                await api.async_close()
                raise ConfigEntryNotReady(
                    f"Could not fetch {coordinator.name} data: {err}"
                ) from err
            _LOGGER.warning("Could not fetch %s data: %s", coordinator.name, err)

    waste_coordinator = KarlstadsenergiWasteCoordinator(
        hass,
        api,
        update_interval,
        entry,
    )
    customer_id = entry.data.get("customer_code") or personnummer
    history_years = int(entry.options.get(CONF_HISTORY_YEARS, DEFAULT_HISTORY_YEARS))
    consumption_coordinator = KarlstadsenergiConsumptionCoordinator(
        hass,
        api,
        max(update_interval // 6, 1),
        entry,
        customer_id=customer_id,
        history_years=history_years,
    )

    # Waste is the primary feature: a non-auth failure with no cache aborts
    # setup (ConfigEntryNotReady) so HA retries.
    await _refresh(waste_coordinator, critical=True)

    # Consumption: a dead/expired session must surface reauth (handled inside
    # _refresh). A non-auth failure with no cache is logged and setup continues
    # so waste keeps working even if the electricity API is down.
    await _refresh(consumption_coordinator)

    # District heating coordinator: reads the base model from the electricity
    # coordinator to avoid duplicate page visits and API calls.
    district_heating_coordinator = KarlstadsenergiDistrictHeatingCoordinator(
        hass,
        api,
        max(update_interval // 6, 1),
        entry,
        electricity_coordinator=consumption_coordinator,
        customer_id=customer_id,
        history_years=history_years,
    )
    await _refresh(district_heating_coordinator)

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
    await _refresh(contract_coordinator)

    # Spot price coordinator (15 min interval, public API, no auth).
    spot_price_coordinator = KarlstadsenergiSpotPriceCoordinator(hass, entry)
    await _refresh(spot_price_coordinator)

    entry.runtime_data = KarlstadsenergiData(
        api=api,
        waste_coordinator=waste_coordinator,
        consumption_coordinator=consumption_coordinator,
        district_heating_coordinator=district_heating_coordinator,
        contract_coordinator=contract_coordinator,
        spot_price_coordinator=spot_price_coordinator,
        setup_options=dict(entry.options),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Heartbeat: keep session alive every 5 minutes. The portal reissues the
    # .PORTALAUTH ticket on each request (sliding expiration), so persist the
    # refreshed cookies here too -- otherwise the saved ticket goes stale
    # between the (infrequent) coordinator updates and a restart loads an
    # expired ticket.
    async def _heartbeat(_now=None) -> None:
        try:
            ok = await api.async_heartbeat()
            if ok:
                _persist_session_cookies(hass, entry, api)
            else:
                _LOGGER.debug("Heartbeat did not keep the session alive")
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


async def async_remove_entry(
    hass: HomeAssistant, entry: KarlstadsenergiConfigEntry
) -> None:
    """Delete the local data cache when the entry is removed."""
    await _DataCache(hass, entry).async_remove()


async def _async_reload_entry(
    hass: HomeAssistant,
    entry: KarlstadsenergiConfigEntry,
) -> None:
    """Reload entry on options change (ignores data-only updates like cookie saves).

    Reauth schedules its own reload explicitly (see config_flow), so the listener
    only needs to handle options changes here.
    """
    if dict(entry.options) != entry.runtime_data.setup_options:
        await hass.config_entries.async_reload(entry.entry_id)
