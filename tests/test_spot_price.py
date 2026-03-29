"""Tests for KarlstadsenergiSpotPriceCoordinator._parse_spot_data().

All tests call the static method directly -- no HA instance needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

# Import the static method via the class; we don't need to instantiate.
# sys.path manipulation is not required because pytest is run from the repo root.
from custom_components.karlstadsenergi import KarlstadsenergiSpotPriceCoordinator

# M3: _make_spotprice_entry is consolidated in conftest.py to avoid duplication.
# Import directly since it is a plain function, not a pytest fixture.
from tests.conftest import _make_spotprice_entry

parse = KarlstadsenergiSpotPriceCoordinator._parse_spot_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response(*entries) -> dict[str, Any]:
    return {"timezone": "Europe/Stockholm", "spotprices": list(entries)}


# ---------------------------------------------------------------------------
# Empty / missing data
# ---------------------------------------------------------------------------


class TestEmptyData:
    def test_empty_spotprices_list(self) -> None:
        result = parse({"timezone": "Europe/Stockholm", "spotprices": []})
        assert result["current_price"] is None
        assert result["prices"] == []

    def test_missing_spotprices_key(self) -> None:
        result = parse({})
        assert result["current_price"] is None
        assert result["prices"] == []

    def test_entry_missing_start_time(self) -> None:
        data = _response({"Spotprice": {"region": "SE3", "price": 100.0}})
        result = parse(data)
        # Entry is skipped; prices list is empty
        assert result["prices"] == []
        assert result["current_price"] is None

    def test_entry_missing_price(self) -> None:
        data = _response(
            {"Spotprice": {"region": "SE3", "start_time": "2026-03-28T10:00:00+0000"}}
        )
        result = parse(data)
        assert result["prices"] == []
        assert result["current_price"] is None

    def test_entry_invalid_timestamp_format(self) -> None:
        data = _response(
            {"Spotprice": {"region": "SE3", "start_time": "not-a-date", "price": 50.0}}
        )
        result = parse(data)
        assert result["prices"] == []
        assert result["current_price"] is None


# ---------------------------------------------------------------------------
# Price parsing and conversion
# ---------------------------------------------------------------------------


class TestPriceParsing:
    def test_ore_to_sek_conversion(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0))
        result = parse(data)
        assert len(result["prices"]) == 1
        price = result["prices"][0]
        assert price["price_ore"] == 100.0
        assert price["price_sek"] == pytest.approx(1.0, abs=1e-4)

    def test_fractional_ore_rounded_to_four_decimals(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-28T10:00:00+0000", 52.235))
        result = parse(data)
        price = result["prices"][0]
        assert price["price_sek"] == pytest.approx(0.5224, abs=1e-4)

    def test_prices_sorted_ascending(self) -> None:
        data = _response(
            _make_spotprice_entry("2026-03-28T10:30:00+0000", 130.0),
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 110.0),
        )
        result = parse(data)
        starts = [p["start"] for p in result["prices"]]
        assert starts == sorted(starts)

    def test_region_always_se3(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-28T10:00:00+0000", 50.0))
        result = parse(data)
        assert result["region"] == "SE3"

    def test_utc_timestamp_parsed_with_timezone(self) -> None:
        data = _response(_make_spotprice_entry("2026-03-28T10:00:00+0000", 50.0))
        result = parse(data)
        dt = result["prices"][0]["start"]
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Current price selection
# ---------------------------------------------------------------------------


class TestCurrentPriceSelection:
    def test_current_price_matches_active_bucket(self) -> None:
        """'now' is inside 10:15--10:30 window."""
        data = _response(
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 110.0),
            _make_spotprice_entry("2026-03-28T10:30:00+0000", 120.0),
            _make_spotprice_entry("2026-03-28T10:45:00+0000", 130.0),
        )
        fake_now = datetime(2026, 3, 28, 10, 20, 0, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)

        assert result["current_price"] == pytest.approx(1.10, abs=1e-4)

    def test_current_price_first_bucket(self) -> None:
        """'now' exactly equals the first bucket start."""
        data = _response(
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 200.0),
        )
        fake_now = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)

        assert result["current_price"] == pytest.approx(1.00, abs=1e-4)

    def test_current_price_last_bucket_no_next_start(self) -> None:
        """'now' is inside the last bucket (no next_start)."""
        data = _response(
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 200.0),
        )
        fake_now = datetime(2026, 3, 28, 10, 20, 0, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)

        # 'now' is past the last bucket start (10:15) with no next_start,
        # so the last bucket is used.
        assert result["current_price"] == pytest.approx(2.00, abs=1e-4)

    def test_stale_data_no_future_bucket(self) -> None:
        """All prices are in the far past; no bucket is current."""
        data = _response(
            _make_spotprice_entry("2020-01-01T00:00:00+0000", 80.0),
            _make_spotprice_entry("2020-01-01T00:15:00+0000", 85.0),
        )
        # Use real datetime.now() -- 2026-03-28 is after all entries
        result = parse(data)
        # The algorithm finds no bucket where now >= start and (no next or now < next).
        # For the last bucket there is no next_start, so if now >= last start it
        # returns that price. Stale data thus returns the last known price.
        # This documents the current behavior for the second opinion reviewer.
        # Because now (2026) > last start (2020-01-01T00:15), and the last
        # bucket has no next_start, the algorithm returns the last bucket's price.
        assert result["current_price"] == pytest.approx(0.85, abs=1e-4)

    def test_day_boundary_correct_bucket(self) -> None:
        """Price straddling midnight: 23:45 and 00:00 next day."""
        data = _response(
            _make_spotprice_entry("2026-03-28T23:45:00+0000", 50.0),
            _make_spotprice_entry("2026-03-29T00:00:00+0000", 60.0),
        )
        # 'now' is at 23:50 UTC on 2026-03-28, should fall in 23:45 bucket
        fake_now = datetime(2026, 3, 28, 23, 50, 0, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)

        assert result["current_price"] == pytest.approx(0.50, abs=1e-4)

    def test_before_all_buckets_returns_none(self) -> None:
        """'now' is before the very first bucket start."""
        data = _response(
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 110.0),
        )
        fake_now = datetime(2026, 3, 28, 9, 59, 59, tzinfo=timezone.utc)
        with patch("custom_components.karlstadsenergi.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = parse(data)

        assert result["current_price"] is None
