"""Tests for the per-bucket spot price list attributes (prices_today/prices_tomorrow)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.karlstadsenergi.sensor import SpotPriceSensor
from tests.test_sensor_entities import _mock_coord

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _utc_buckets(first: datetime, count: int) -> list[dict[str, Any]]:
    """Contiguous 15-minute UTC buckets; the price encodes the index."""
    return [
        {
            "start": first + timedelta(minutes=15 * i),
            "price_sek": round(i / 100, 4),
            "price_ore": float(i),
        }
        for i in range(count)
    ]


def _sensor(prices: list[dict[str, Any]]) -> SpotPriceSensor:
    coord = _mock_coord({"current_price": 1.0, "prices": prices, "region": "SE3"})
    return SpotPriceSensor(coordinator=coord, customer_id="CUST01")


def _attrs_at(prices: list[dict[str, Any]], local_now: datetime) -> dict[str, Any]:
    sensor = _sensor(prices)
    with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
        mock_dt.now.return_value = local_now
        return sensor.extra_state_attributes


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=STOCKHOLM)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 11, 10), 96),  # normal day
        (date(2026, 3, 29), 92),  # spring forward (CET -> CEST)
        (date(2026, 10, 25), 100),  # fall back (CEST -> CET)
    ],
)
def test_prices_today_bucketed_by_local_day(day: date, expected: int) -> None:
    midnight = _local_midnight(day)
    next_midnight = _local_midnight(day + timedelta(days=1))
    # Three days of buckets starting two hours before local midnight.
    prices = _utc_buckets((midnight - timedelta(hours=2)).astimezone(UTC), 4 * 24 * 3)
    attrs = _attrs_at(prices, midnight + timedelta(hours=12))

    today = attrs["prices_today"]
    assert len(today) == expected
    assert today[0]["start"] == midnight.isoformat()
    # Last bucket of today ends where tomorrow begins (next local midnight).
    assert today[-1]["end"] == next_midnight.isoformat()
    assert attrs["prices_tomorrow"][0]["start"] == next_midnight.isoformat()
    for a, b in pairwise(today):
        assert a["end"] == b["start"]
    # The lists agree with the existing summary attributes.
    assert attrs["today_min"] == min(b["price"] for b in today)
    assert attrs["today_max"] == max(b["price"] for b in today)
    assert attrs["tomorrow_min"] == min(b["price"] for b in attrs["prices_tomorrow"])


def test_prices_entry_format() -> None:
    start = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)
    prices = [
        {"start": start, "price_sek": 3.3716, "price_ore": 337.16},
        {"start": start + timedelta(minutes=15), "price_sek": 3.1, "price_ore": 310.0},
    ]
    attrs = _attrs_at(prices, datetime(2026, 11, 10, 14, 5, tzinfo=STOCKHOLM))
    assert attrs["prices_today"][0] == {
        "start": "2026-11-10T14:00:00+01:00",
        "end": "2026-11-10T14:15:00+01:00",
        "price": 3.3716,
    }


def test_last_bucket_end_is_start_plus_15_min() -> None:
    prices = _utc_buckets(datetime(2026, 11, 10, 22, 45, tzinfo=UTC), 1)  # 23:45 local
    attrs = _attrs_at(prices, datetime(2026, 11, 10, 23, 50, tzinfo=STOCKHOLM))
    assert attrs["prices_today"][-1]["end"] == "2026-11-11T00:00:00+01:00"


def test_prices_tomorrow_empty_until_published() -> None:
    midnight = _local_midnight(date(2026, 11, 10))
    prices = _utc_buckets(midnight.astimezone(UTC), 96)
    attrs = _attrs_at(prices, midnight + timedelta(hours=10))
    assert len(attrs["prices_today"]) == 96
    assert attrs["prices_tomorrow"] == []
    assert "tomorrow_min" not in attrs


def test_yesterday_buckets_excluded() -> None:
    midnight = _local_midnight(date(2026, 11, 10))
    prices = _utc_buckets((midnight - timedelta(days=1)).astimezone(UTC), 96 * 2)
    attrs = _attrs_at(prices, midnight + timedelta(hours=1))
    assert len(attrs["prices_today"]) == 96
    assert attrs["prices_today"][0]["start"] == midnight.isoformat()


def test_lists_empty_without_prices() -> None:
    attrs = _attrs_at([], datetime(2026, 11, 10, 12, 0, tzinfo=STOCKHOLM))
    assert attrs["prices_today"] == []
    assert attrs["prices_tomorrow"] == []


def test_lists_excluded_from_recorder() -> None:
    unrecorded = _sensor([])._unrecorded_attributes
    assert {"prices_today", "prices_tomorrow"} <= unrecorded
    assert "today_average" not in unrecorded
