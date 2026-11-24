"""Optional detail fetches: warn once per outage, keep the last good data.

Covers #49 (a failing hourly/fee/monthly/flow/dT fetch is logged at warning
level once, and its recovery at info level) and #50 (a failing or empty part
keeps the last good value and is listed in ``stale_parts``; entities reading
that part report ``data_stale``).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi import (
    KarlstadsenergiConsumptionCoordinator,
    KarlstadsenergiDistrictHeatingCoordinator,
)
from custom_components.karlstadsenergi.api import (
    KarlstadsenergiApiError,
    KarlstadsenergiAuthError,
)
from custom_components.karlstadsenergi.entity import KarlstadsenergiEntity

from .test_integration import _make_api


def _chart(series_id: str) -> dict[str, Any]:
    return {"DetailedConsumptionChart": {"SeriesList": [{"id": series_id, "data": [{"y": 1.0}]}]}}


HOURLY = _chart("h")
FEES = _chart("SUM")
MONTHLY = _chart("m")

# Responses without usable data: the endpoint answers with a chart dict even
# when there is nothing in it.
_EMPTY_RESPONSES = {
    "empty": {},
    "empty_chart": {"DetailedConsumptionChart": {"SeriesList": []}},
    "empty_series": {"DetailedConsumptionChart": {"SeriesList": [{"id": "x", "data": []}]}},
}

_ELECTRICITY_FETCHERS = {
    "hourly": "async_get_hourly_consumption",
    "fee_data": "async_get_fee_consumption",
    "monthly_kwh": "async_get_monthly_consumption",
}


def _coordinator(customer_id: str = "") -> tuple[KarlstadsenergiConsumptionCoordinator, MagicMock]:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.data = {"session_cookies": {}}
    api = _make_api()
    api.async_get_consumption = AsyncMock(return_value={"ConsumptionModel": {"SiteId": "s1"}})
    api.async_get_hourly_consumption = AsyncMock(return_value=HOURLY)
    api.async_get_fee_consumption = AsyncMock(return_value=FEES)
    api.async_get_monthly_consumption = AsyncMock(return_value=MONTHLY)
    coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry, customer_id=customer_id)
    return coord, api


def _good() -> dict[str, Any]:
    return {"hourly": HOURLY, "fee_data": FEES, "monthly_kwh": MONTHLY}


# ---------------------------------------------------------------------------
# Matrix: outcome of one part x whether a previous value exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("part", list(_ELECTRICITY_FETCHERS))
@pytest.mark.parametrize("outcome", ["error", *_EMPTY_RESPONSES])
@pytest.mark.parametrize("has_previous", [True, False])
async def test_failed_or_empty_part_keeps_last_good(
    part: str, outcome: str, has_previous: bool
) -> None:
    coord, api = _coordinator()
    if has_previous:
        coord.data = {"consumption": {}, **_good(), "stale_parts": []}
    fetcher = getattr(api, _ELECTRICITY_FETCHERS[part])
    if outcome == "error":
        fetcher.side_effect = KarlstadsenergiApiError("API returned status 500")
    else:
        fetcher.return_value = _EMPTY_RESPONSES[outcome]

    result = await coord._async_update_data()

    if has_previous:
        assert result[part] == _good()[part]
        assert result["stale_parts"] == [part]
    else:
        assert result[part] == ({} if outcome == "error" else _EMPTY_RESPONSES[outcome])
        assert result["stale_parts"] == []
    # The other parts are fresh and never stale.
    for other in _ELECTRICITY_FETCHERS:
        if other != part:
            assert result[other] == _good()[other]


@pytest.mark.asyncio
async def test_all_parts_fresh_means_nothing_stale() -> None:
    coord, _api = _coordinator()
    coord.data = {"consumption": {}, "hourly": {"old": 1}, "stale_parts": ["hourly"]}

    result = await coord._async_update_data()

    assert result["hourly"] == HOURLY
    assert result["stale_parts"] == []


@pytest.mark.asyncio
async def test_auth_error_in_a_part_still_fails_the_update() -> None:
    from homeassistant.exceptions import ConfigEntryAuthFailed

    coord, api = _coordinator()
    api.async_get_fee_consumption.side_effect = KarlstadsenergiAuthError("expired")

    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


# ---------------------------------------------------------------------------
# Logging: one warning per outage, info on recovery (#49)
# ---------------------------------------------------------------------------


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == level]


@pytest.mark.asyncio
async def test_warns_once_per_outage_and_logs_recovery(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.karlstadsenergi")
    coord, api = _coordinator(customer_id="c1")
    coord._async_import_consumption_statistics = AsyncMock()
    coord._async_import_fee_statistics = AsyncMock()
    api.async_get_hourly_consumption.side_effect = KarlstadsenergiApiError(
        "API returned status 500"
    )

    await coord._async_update_data()
    await coord._async_update_data()

    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "hourly" in warnings[0]
    assert "status 500" in warnings[0]
    assert not _records(caplog, logging.INFO)

    caplog.clear()
    api.async_get_hourly_consumption.side_effect = None
    await coord._async_update_data()

    assert not _records(caplog, logging.WARNING)
    assert any("hourly" in m and "works again" in m for m in _records(caplog, logging.INFO))

    # A new outage warns again.
    caplog.clear()
    api.async_get_hourly_consumption.side_effect = KarlstadsenergiApiError("boom")
    await coord._async_update_data()
    assert len(_records(caplog, logging.WARNING)) == 1


@pytest.mark.asyncio
async def test_empty_response_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.karlstadsenergi")
    coord, api = _coordinator(customer_id="c1")
    coord._async_import_fee_statistics = AsyncMock()
    # An account without hourly metering gets an empty response every time.
    api.async_get_hourly_consumption.return_value = {}

    await coord._async_update_data()

    assert not _records(caplog, logging.WARNING)


# ---------------------------------------------------------------------------
# Retained data never drives statistics imports or the backfill flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retained_data_is_not_imported_and_does_not_finish_backfill() -> None:
    coord, api = _coordinator(customer_id="c1")
    # Seeded from the on-disk cache after a restart.
    coord.data = {"consumption": {}, **_good(), "stale_parts": []}
    api.async_get_hourly_consumption.side_effect = KarlstadsenergiApiError("500")
    api.async_get_fee_consumption.side_effect = KarlstadsenergiApiError("500")

    with (
        patch.object(coord, "_async_import_consumption_statistics", AsyncMock()) as hourly_import,
        patch.object(coord, "_async_import_fee_statistics", AsyncMock()) as fee_import,
    ):
        result = await coord._async_update_data()

    hourly_import.assert_not_awaited()
    fee_import.assert_not_awaited()
    assert coord._backfill_done is False
    assert result["fee_data"] == FEES
    assert sorted(result["stale_parts"]) == ["fee_data", "hourly"]

    # Only a fresh result finishes the backfill, and it is imported.
    api.async_get_hourly_consumption.side_effect = None
    api.async_get_fee_consumption.side_effect = None
    with (
        patch.object(coord, "_async_import_consumption_statistics", AsyncMock()) as hourly_import,
        patch.object(coord, "_async_import_fee_statistics", AsyncMock()),
    ):
        await coord._async_update_data()
    hourly_import.assert_awaited_once_with(HOURLY)
    assert coord._backfill_done is True


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", ["empty_chart", "empty_series"])
async def test_empty_chart_does_not_finish_backfill(empty: str) -> None:
    coord, api = _coordinator()
    api.async_get_hourly_consumption.return_value = _EMPTY_RESPONSES[empty]
    api.async_get_fee_consumption.return_value = _EMPTY_RESPONSES[empty]

    await coord._async_update_data()

    assert coord._backfill_done is False


# ---------------------------------------------------------------------------
# District heating: same behaviour for all five parts
# ---------------------------------------------------------------------------

_DH_FETCHES = {
    "hourly": ("async_get_hourly_consumption", None),
    "monthly_kwh": ("async_get_monthly_consumption", None),
    "fee_data": ("async_get_fee_consumption", None),
    "flow": ("async_get_consumption_with_model", "Flow"),
    "dt": ("async_get_consumption_with_model", "DT"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("part", list(_DH_FETCHES))
async def test_district_heating_part_keeps_last_good(part: str) -> None:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.data = {"session_cookies": {}}
    api = _make_api()
    api.async_get_consumption = AsyncMock(
        return_value={
            "ConsumptionModel": {
                "SiteId": "s1",
                "SelectedSiteGroupNode": {"Utilities": [{"UtilityId": "F"}]},
            }
        }
    )
    good = {name: _chart(name) for name in _DH_FETCHES}
    api.async_get_hourly_consumption = AsyncMock(return_value=good["hourly"])
    api.async_get_monthly_consumption = AsyncMock(return_value=good["monthly_kwh"])
    api.async_get_fee_consumption = AsyncMock(return_value=good["fee_data"])

    fetcher_name, load_option = _DH_FETCHES[part]

    async def _with_model(model: dict) -> dict:
        option = (model.get("Loadoptions") or [None])[0]
        if part in ("flow", "dt") and option == load_option:
            raise KarlstadsenergiApiError("500")
        return {"Flow": good["flow"], "DT": good["dt"]}.get(option, _chart("daily"))

    api.async_get_consumption_with_model = AsyncMock(side_effect=_with_model)
    if part not in ("flow", "dt"):
        getattr(api, fetcher_name).side_effect = KarlstadsenergiApiError("500")

    coord = KarlstadsenergiDistrictHeatingCoordinator(
        hass, api, 1, entry, electricity_coordinator=None
    )
    coord.data = {"available": True, "consumption": {}, **good, "stale_parts": []}

    result = await coord._async_update_data()

    assert result[part] == good[part]
    assert result["stale_parts"] == [part]


# ---------------------------------------------------------------------------
# Entities report data_stale only for the parts they read
# ---------------------------------------------------------------------------


class _Entity(KarlstadsenergiEntity):
    def __init__(self, coordinator: MagicMock, parts: tuple[str, ...]) -> None:
        self.coordinator = coordinator
        self._data_parts = parts


@pytest.mark.parametrize(
    ("parts", "stale_parts", "last_update_success", "expected"),
    [
        (("fee_data",), ["fee_data"], True, True),
        (("fee_data",), ["hourly"], True, False),
        (("hourly", "monthly_kwh"), ["monthly_kwh"], True, True),
        ((), ["fee_data"], True, False),
        (("fee_data",), [], False, True),
        (("fee_data",), [], True, False),
    ],
)
def test_entity_data_stale_follows_its_parts(
    parts: tuple[str, ...], stale_parts: list[str], last_update_success: bool, expected: bool
) -> None:
    coordinator = MagicMock()
    coordinator.data = {"stale_parts": stale_parts}
    coordinator.last_update_success = last_update_success
    coordinator.last_success_time = None

    assert _Entity(coordinator, parts)._staleness_attrs["data_stale"] is expected


def test_entity_without_stale_parts_key_uses_update_success() -> None:
    coordinator = MagicMock()
    coordinator.data = {"services": []}  # waste data has no stale_parts
    coordinator.last_update_success = True
    coordinator.last_success_time = None

    assert _Entity(coordinator, ("fee_data",))._staleness_attrs["data_stale"] is False
