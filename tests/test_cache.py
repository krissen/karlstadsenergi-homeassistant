"""Tests for the local data-cache fallback.

Covers the JSON datetime round-trip and the setup behaviour: with a cache
present, a dead session at setup must NOT abort -- entities keep their last
values and a reauth flow is still started; with no cache the strict
abort-and-reauth behaviour is preserved.

Unit-level: no live HA instance. Mirrors the mocking style of
test_integration.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi import (
    KarlstadsenergiData,
    _DataCache,
    _json_decode,
    _json_encode,
    async_setup_entry,
)
from custom_components.karlstadsenergi.api import (
    AUTH_BANKID,
    KarlstadsenergiAuthError,
)
from custom_components.karlstadsenergi.const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed


# ---------------------------------------------------------------------------
# JSON datetime round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_datetime_roundtrip(self) -> None:
        dt = datetime(2026, 3, 28, 10, 15, tzinfo=timezone.utc)
        encoded = _json_encode(dt)
        assert encoded == {"__dt__": dt.isoformat()}
        # must survive a real json dump/load
        restored = _json_decode(json.loads(json.dumps(encoded)))
        assert restored == dt
        assert isinstance(restored, datetime)

    def test_date_roundtrip(self) -> None:
        d = date(2026, 6, 9)
        encoded = _json_encode(d)
        assert encoded == {"__date__": d.isoformat()}
        restored = _json_decode(json.loads(json.dumps(encoded)))
        assert restored == d
        assert isinstance(restored, date) and not isinstance(restored, datetime)

    def test_spot_price_payload_roundtrip(self) -> None:
        """The one real datetime in coordinator data: prices[*]['start']."""
        data = {
            "current_price": 0.52,
            "prices": [
                {
                    "start": datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc),
                    "price_ore": 45.1,
                    "price_sek": 0.451,
                },
                {
                    "start": datetime(2026, 3, 28, 8, 15, tzinfo=timezone.utc),
                    "price_ore": 47.3,
                    "price_sek": 0.473,
                },
            ],
            "region": "SE3",
            "stale": False,
        }
        restored = _json_decode(json.loads(json.dumps(_json_encode(data))))
        assert restored == data
        assert all(isinstance(p["start"], datetime) for p in restored["prices"])

    def test_plain_values_pass_through(self) -> None:
        data = {
            "services": [{"FlexServiceId": 42, "Name": "Mat"}],
            "dates": {"42": "2026-04-15"},  # waste dates stay strings
            "n": 5,
            "f": 1.5,
            "none": None,
            "flag": True,
        }
        # No datetimes -> encode is a structural identity, json-safe.
        encoded = _json_encode(data)
        assert encoded == data
        assert _json_decode(json.loads(json.dumps(encoded))) == data

    def test_full_cache_state_roundtrip(self) -> None:
        state = {
            f"{DOMAIN}_waste": {
                "data": {
                    "services": [],
                    "dates": {"1": "2026-04-15"},
                    "next_dates": [],
                },
                "last_success_time": datetime(2026, 6, 8, 7, 45, tzinfo=timezone.utc),
            },
            f"{DOMAIN}_spot_price": {
                "data": {
                    "current_price": 0.5,
                    "prices": [
                        {
                            "start": datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc),
                            "price_sek": 0.5,
                            "price_ore": 50.0,
                        }
                    ],
                    "region": "SE3",
                    "stale": False,
                },
                "last_success_time": datetime(2026, 6, 8, 7, 45, tzinfo=timezone.utc),
            },
        }
        restored = _json_decode(json.loads(json.dumps(_json_encode(state))))
        assert restored == state


class TestPruneHeavySeries:
    def test_record_drops_hourly_flow_dt(self) -> None:
        with patch("custom_components.karlstadsenergi.Store"):
            cache = _DataCache(MagicMock(), MagicMock(entry_id="x"))
        data = {
            "consumption": {"ConsumptionModel": {"SiteId": "s"}},
            "monthly_kwh": {"x": 1},
            "fee_data": {"y": 2},
            "hourly": {"big": list(range(1000))},
            "flow": {"big": list(range(1000))},
            "dt": {"big": list(range(1000))},
        }
        cache.record(
            "karlstadsenergi_consumption",
            data,
            datetime(2026, 6, 8, tzinfo=timezone.utc),
        )
        cached = cache._state["karlstadsenergi_consumption"]["data"]
        # heavy series dropped...
        assert "hourly" not in cached
        assert "flow" not in cached
        assert "dt" not in cached
        # ...lightweight, state-driving keys kept...
        assert "consumption" in cached
        assert "monthly_kwh" in cached
        assert "fee_data" in cached
        # ...and the live data passed in is NOT mutated.
        assert "hourly" in data


# ---------------------------------------------------------------------------
# Setup behaviour with / without cache
# ---------------------------------------------------------------------------


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_PERSONNUMMER: "199001011234",
        CONF_AUTH_METHOD: AUTH_BANKID,
        "session_cookies": {"ASP.NET_SessionId": "abc", ".PORTALAUTH": "x"},
    }
    entry.options = {}
    entry.runtime_data = None
    entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_start_reauth = MagicMock()
    return entry


def _make_api_all_auth_fail() -> MagicMock:
    """An API whose every portal call fails with an auth error (dead session)."""
    api = MagicMock()
    api.get_session_cookies = MagicMock(return_value={})
    api.set_session_cookies = MagicMock()
    api.authenticate = AsyncMock(side_effect=KarlstadsenergiAuthError("dead"))
    api.async_close = AsyncMock()
    api.async_heartbeat = AsyncMock()
    err = KarlstadsenergiAuthError("session expired")
    for name in (
        "async_get_flex_services",
        "async_get_next_flex_dates",
        "async_get_consumption",
        "async_get_hourly_consumption",
        "async_get_fee_consumption",
        "async_get_monthly_consumption",
        "async_get_consumption_with_model",
        "async_get_contract_details",
    ):
        setattr(api, name, AsyncMock(side_effect=err))
    return api


def _fake_cache_cls(payload: dict):
    """Return a _DataCache stand-in whose async_load yields ``payload``."""

    class _Fake:
        def __init__(self, *_a, **_k) -> None:
            self._state = dict(payload)

        async def async_load(self) -> dict:
            return dict(payload)

        def record(self, name, data, last_success_time) -> None:
            self._state[name] = {"data": data, "last_success_time": last_success_time}

        async def async_remove(self) -> None:
            pass

    return _Fake


WASTE_DATA = {
    "services": [{"FlexServiceId": 1}],
    "dates": {"1": "2026-06-09"},
    "next_dates": [],
}


@pytest.mark.asyncio
async def test_cache_present_survives_dead_session_and_starts_reauth() -> None:
    """With a cache, a dead session must not abort setup; reauth still starts."""
    hass = _make_hass()
    entry = _make_entry()
    api = _make_api_all_auth_fail()
    cached = {
        f"{DOMAIN}_waste": {
            "data": WASTE_DATA,
            "last_success_time": datetime(2026, 6, 8, 7, 45, tzinfo=timezone.utc),
        }
    }

    with (
        patch(
            "custom_components.karlstadsenergi.KarlstadsenergiApi",
            return_value=api,
        ),
        patch(
            "custom_components.karlstadsenergi._DataCache",
            _fake_cache_cls(cached),
        ),
        patch(
            "custom_components.karlstadsenergi.async_track_time_interval",
            return_value=MagicMock(),
        ),
    ):
        result = await async_setup_entry(hass, entry)

    # Setup succeeded (entities load with cached values, not unavailable)...
    assert result is True
    assert isinstance(entry.runtime_data, KarlstadsenergiData)
    # ...the waste coordinator kept its seeded (stale) data...
    assert entry.runtime_data.waste_coordinator.data == WASTE_DATA
    assert entry.runtime_data.waste_coordinator.last_update_success is False
    # ...and the "action needed" reauth prompt was still triggered.
    assert entry.async_start_reauth.called


@pytest.mark.asyncio
async def test_no_cache_dead_session_aborts_with_reauth() -> None:
    """Without a cache, a dead session aborts setup via ConfigEntryAuthFailed."""
    hass = _make_hass()
    entry = _make_entry()
    api = _make_api_all_auth_fail()

    with (
        patch(
            "custom_components.karlstadsenergi.KarlstadsenergiApi",
            return_value=api,
        ),
        patch(
            "custom_components.karlstadsenergi._DataCache",
            _fake_cache_cls({}),
        ),
        patch(
            "custom_components.karlstadsenergi.async_track_time_interval",
            return_value=MagicMock(),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)
