"""Tests for coordinator logic in __init__.py.

Tests are unit-level: no HA instance required. The _CookieSavingCoordinator
base class and _save_cookies are tested via the concrete subclasses using
minimal MagicMock setups.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi import (
    KarlstadsenergiSpotPriceCoordinator,
    KarlstadsenergiWasteCoordinator,
)

# Re-use the shared spot-price helper from conftest
from tests.conftest import _make_spotprice_entry

parse = KarlstadsenergiSpotPriceCoordinator._parse_spot_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.config_entries = MagicMock()
    return hass


def _make_entry(data: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = data or {"session_cookies": {}}
    return entry


def _make_api() -> MagicMock:
    api = MagicMock()
    api.get_session_cookies = MagicMock(return_value={})
    return api


def _response(*entries: dict) -> dict[str, Any]:
    return {"timezone": "Europe/Stockholm", "spotprices": list(entries)}


# ---------------------------------------------------------------------------
# _parse_spot_data -- valid data
# ---------------------------------------------------------------------------


class TestParseSpotDataValid:
    def test_returns_region_se3(self) -> None:
        data = _response(
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 52.5),
        )
        result = parse(data)
        assert result["region"] == "SE3"

    def test_ore_to_sek_conversion(self) -> None:
        data = _response(
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 52.5),
        )
        result = parse(data)
        assert result["prices"][0]["price_sek"] == pytest.approx(0.525, abs=1e-4)
        assert result["prices"][0]["price_ore"] == 52.5

    def test_two_entries_produce_two_price_points(self) -> None:
        data = _response(
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 52.5),
            _make_spotprice_entry("2026-03-29T11:00:00+0000", 48.3),
        )
        result = parse(data)
        assert len(result["prices"]) == 2

    def test_prices_sorted_ascending_by_start(self) -> None:
        data = _response(
            _make_spotprice_entry("2026-03-29T11:00:00+0000", 48.3),
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 52.5),
        )
        result = parse(data)
        starts = [p["start"] for p in result["prices"]]
        assert starts == sorted(starts)

    def test_each_price_point_has_required_keys(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-29T10:00:00+0000", 100.0))
        result = parse(data)
        p = result["prices"][0]
        assert "start" in p
        assert "price_ore" in p
        assert "price_sek" in p

    def test_start_time_has_timezone_info(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-29T10:00:00+0000", 100.0))
        result = parse(data)
        dt = result["prices"][0]["start"]
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _parse_spot_data -- empty / missing data
# ---------------------------------------------------------------------------


class TestParseSpotDataEmpty:
    def test_empty_spotprices_returns_none_current_price(self) -> None:
        result = parse({"spotprices": []})
        assert result["current_price"] is None

    def test_empty_spotprices_returns_empty_prices_list(self) -> None:
        result = parse({"spotprices": []})
        assert result["prices"] == []

    def test_missing_spotprices_key_returns_defaults(self) -> None:
        result = parse({})
        assert result["current_price"] is None
        assert result["prices"] == []

    def test_entry_missing_start_time_is_skipped(self) -> None:
        data = {"spotprices": [{"Spotprice": {"region": "SE3", "price": 100.0}}]}
        result = parse(data)
        assert result["prices"] == []

    def test_entry_missing_price_is_skipped(self) -> None:
        data = {
            "spotprices": [
                {
                    "Spotprice": {
                        "region": "SE3",
                        "start_time": "2026-03-29T10:00:00+0000",
                    }
                }
            ]
        }
        result = parse(data)
        assert result["prices"] == []

    def test_entry_invalid_timestamp_is_skipped(self) -> None:
        data = {
            "spotprices": [
                {
                    "Spotprice": {
                        "region": "SE3",
                        "start_time": "not-a-date",
                        "price": 50.0,
                    }
                }
            ]
        }
        result = parse(data)
        assert result["prices"] == []

    def test_spotprices_explicit_null_returns_defaults(self) -> None:
        result = parse({"spotprices": None})
        assert result["current_price"] is None
        assert result["prices"] == []

    def test_spotprice_entry_explicit_null_is_skipped(self) -> None:
        data = {
            "spotprices": [
                {"Spotprice": None},
                _make_spotprice_entry("2026-03-29T10:00:00+0000", 52.5),
            ]
        }
        result = parse(data)
        assert len(result["prices"]) == 1


# ---------------------------------------------------------------------------
# _parse_spot_data -- current price selection (mocked time)
# ---------------------------------------------------------------------------


class TestParseSpotDataCurrentPrice:
    def test_current_price_is_none_before_all_buckets(self) -> None:
        from datetime import datetime, timezone

        data = _response(
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-29T10:15:00+0000", 110.0),
        )
        fake_now = datetime(2026, 3, 29, 9, 59, 59, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)
        assert result["current_price"] is None

    def test_current_price_matches_active_bucket(self) -> None:
        from datetime import datetime, timezone

        data = _response(
            _make_spotprice_entry("2026-03-29T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-29T10:15:00+0000", 110.0),
            _make_spotprice_entry("2026-03-29T10:30:00+0000", 120.0),
        )
        fake_now = datetime(2026, 3, 29, 10, 20, 0, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)
        assert result["current_price"] == pytest.approx(1.10, abs=1e-4)


# ---------------------------------------------------------------------------
# _save_cookies -- cookie persistence on update
# ---------------------------------------------------------------------------


class TestSaveCookies:
    def test_save_cookies_updates_entry_when_cookies_changed(self) -> None:
        hass = _make_hass()
        api = _make_api()
        api.get_session_cookies = MagicMock(
            return_value={"ASP.NET_SessionId": "newval", ".PORTALAUTH": "auth"}
        )

        entry = _make_entry(
            {"session_cookies": {"ASP.NET_SessionId": "oldval", ".PORTALAUTH": "auth"}}
        )

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies()

        hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["session_cookies"] == {
            "ASP.NET_SessionId": "newval",
            ".PORTALAUTH": "auth",
        }

    def test_save_cookies_does_nothing_when_cookies_unchanged(self) -> None:
        hass = _make_hass()
        api = _make_api()
        same_cookies = {"ASP.NET_SessionId": "samevalue"}
        api.get_session_cookies = MagicMock(return_value=same_cookies)

        entry = _make_entry({"session_cookies": same_cookies})

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies()

        hass.config_entries.async_update_entry.assert_not_called()

    def test_save_cookies_does_nothing_when_empty_cookies(self) -> None:
        hass = _make_hass()
        api = _make_api()
        api.get_session_cookies = MagicMock(return_value={})

        entry = _make_entry({})

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies()

        hass.config_entries.async_update_entry.assert_not_called()

    def test_save_cookies_skips_partial_cookies(self) -> None:
        # Only ASP.NET_SessionId present -- .PORTALAUTH missing.
        # Partial cookies must NOT be persisted (would invalidate the session).
        hass = _make_hass()
        api = _make_api()
        api.get_session_cookies = MagicMock(return_value={"ASP.NET_SessionId": "val"})

        entry = _make_entry({"session_cookies": {}})

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies()

        hass.config_entries.async_update_entry.assert_not_called()


# ---------------------------------------------------------------------------
# KarlstadsenergiWasteCoordinator -- _async_update_data
# ---------------------------------------------------------------------------


class TestWasteCoordinatorUpdate:
    @pytest.mark.asyncio
    async def test_returns_services_and_dates_on_success(self) -> None:
        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        service = {
            "FlexServiceId": 42,
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": "Hushållsavfall",
            "FlexServiceContainTypeValue": "Mat- och restavfall",
        }
        api.async_get_flex_services = AsyncMock(return_value=[service])
        api.async_get_flex_dates = AsyncMock(return_value={"42": "2026-04-15"})
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        result = await coord._async_update_data()

        assert result["services"] == [service]
        assert result["dates"] == {"42": "2026-04-15"}
        assert result["next_dates"] == []

    @pytest.mark.asyncio
    async def test_uses_fallback_when_services_empty(self) -> None:

        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        fallback = [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]
        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(return_value=fallback)

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        result = await coord._async_update_data()

        assert result["services"] == []
        assert result["next_dates"] == fallback

    @pytest.mark.asyncio
    async def test_skips_inactive_services(self) -> None:
        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        active = {
            "FlexServiceId": 1,
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": "X",
        }
        inactive = {
            "FlexServiceId": 2,
            "FSStatusName": "Inaktiv",
            "FlexServiceGroupName": "X",
        }
        api.async_get_flex_services = AsyncMock(return_value=[active, inactive])
        api.async_get_flex_dates = AsyncMock(return_value={})
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        result = await coord._async_update_data()

        service_ids = [s["FlexServiceId"] for s in result["services"]]
        assert 1 in service_ids
        assert 2 not in service_ids

    @pytest.mark.asyncio
    async def test_skips_skip_group_names(self) -> None:
        from custom_components.karlstadsenergi.const import SKIP_GROUP_NAMES

        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        skip_group = list(SKIP_GROUP_NAMES)[0]
        normal = {
            "FlexServiceId": 1,
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": "Hushållsavfall",
        }
        billing = {
            "FlexServiceId": 2,
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": skip_group,
        }
        api.async_get_flex_services = AsyncMock(return_value=[normal, billing])
        api.async_get_flex_dates = AsyncMock(return_value={})
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        result = await coord._async_update_data()

        service_ids = [s["FlexServiceId"] for s in result["services"]]
        assert 1 in service_ids
        assert 2 not in service_ids

    @pytest.mark.asyncio
    async def test_raises_config_entry_auth_failed_on_auth_error(self) -> None:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiAuthError

        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        api.async_get_flex_services = AsyncMock(
            side_effect=KarlstadsenergiAuthError("session expired")
        )
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_skips_services_missing_flex_service_id(self) -> None:
        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        good = {
            "FlexServiceId": 1,
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": "X",
        }
        bad = {
            "FSStatusName": "Aktiv",
            "FlexServiceGroupName": "Y",
            # no FlexServiceId
        }
        api.async_get_flex_services = AsyncMock(return_value=[good, bad])
        api.async_get_flex_dates = AsyncMock(return_value={})
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        await coord._async_update_data()

        # bad service passes filtering (Aktiv, not in SKIP_GROUP_NAMES) but
        # service_ids list comprehension must skip it instead of raising KeyError
        api.async_get_flex_dates.assert_called_once()
        ids_arg = api.async_get_flex_dates.call_args[0][0]
        assert 1 in ids_arg

    @pytest.mark.asyncio
    async def test_saves_cookies_after_successful_update(self) -> None:
        hass = _make_hass()
        api = _make_api()
        api.get_session_cookies = MagicMock(return_value={"ASP.NET_SessionId": "new"})
        entry = _make_entry({"session_cookies": {}})

        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies = MagicMock()

        await coord._async_update_data()

        coord._save_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_saves_cookies_even_on_update_failure(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = _make_hass()
        api = _make_api()
        entry = _make_entry()

        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )

        coord = KarlstadsenergiWasteCoordinator(hass, api, 6, entry)
        coord._save_cookies = MagicMock()

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        coord._save_cookies.assert_called_once()
