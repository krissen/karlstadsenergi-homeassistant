"""Shared pytest fixtures for Karlstadsenergi integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture file by name (without .json extension)."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Spot price fixtures
# ---------------------------------------------------------------------------


def _make_spotprice_entry(
    start_utc: str,
    price: float,
    region: str = "SE3",
) -> dict[str, Any]:
    """Build one item in the Evado spotprices list."""
    return {
        "Spotprice": {
            "region": region,
            "start_time": start_utc,
            "end_time": "",
            "price": price,
            "modified": "",
        }
    }


@pytest.fixture
def spot_price_response_normal() -> dict[str, Any]:
    """A realistic Evado response with four 15-min price buckets."""
    return {
        "timezone": "Europe/Stockholm",
        "spotprices": [
            _make_spotprice_entry("2026-03-28T10:00:00+0000", 100.0),
            _make_spotprice_entry("2026-03-28T10:15:00+0000", 110.0),
            _make_spotprice_entry("2026-03-28T10:30:00+0000", 120.0),
            _make_spotprice_entry("2026-03-28T10:45:00+0000", 130.0),
        ],
    }


@pytest.fixture
def spot_price_response_empty() -> dict[str, Any]:
    """Evado response with no spotprices list."""
    return {"timezone": "Europe/Stockholm", "spotprices": []}


@pytest.fixture
def spot_price_response_day_boundary() -> dict[str, Any]:
    """Prices straddling midnight UTC (23:45 and 00:00 the next day)."""
    return {
        "timezone": "Europe/Stockholm",
        "spotprices": [
            _make_spotprice_entry("2026-03-28T23:45:00+0000", 50.0),
            _make_spotprice_entry("2026-03-29T00:00:00+0000", 60.0),
        ],
    }


@pytest.fixture
def spot_price_response_stale() -> dict[str, Any]:
    """All prices are from the past -- none match 'now'."""
    return {
        "timezone": "Europe/Stockholm",
        "spotprices": [
            _make_spotprice_entry("2020-01-01T00:00:00+0000", 80.0),
            _make_spotprice_entry("2020-01-01T00:15:00+0000", 85.0),
        ],
    }


# ---------------------------------------------------------------------------
# Fee / consumption fixtures
# ---------------------------------------------------------------------------


def _make_fee_data(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a list of series dicts into the GetConsumption fee response shape."""
    return {
        "DetailedConsumptionChart": {
            "SeriesList": series,
        }
    }


def _make_series(
    series_id: str, data_points: list[tuple[str, float]]
) -> dict[str, Any]:
    """Build one series entry. data_points is list of (dateInterval, y) tuples."""
    return {
        "id": series_id,
        "data": [{"dateInterval": d, "y": v} for d, v in data_points],
    }


@pytest.fixture
def fee_data_typical() -> dict[str, Any]:
    """Fee data with three series, each covering one month."""
    return _make_fee_data(
        [
            _make_series(
                "ConsumptionFee",
                [
                    ("2026-02-01", 150.50),
                    ("2026-02-15", 200.00),
                ],
            ),
            _make_series(
                "PowerFee",
                [
                    ("2026-02-01", 80.00),
                ],
            ),
            _make_series(
                "VAT",
                [
                    ("2026-02-01", 57.625),
                ],
            ),
        ]
    )


@pytest.fixture
def fee_data_multi_month() -> dict[str, Any]:
    """Fee data spanning two calendar months."""
    return _make_fee_data(
        [
            _make_series(
                "ConsumptionFee",
                [
                    ("2026-01-20", 100.0),
                    ("2026-02-05", 200.0),
                ],
            ),
        ]
    )


@pytest.fixture
def fee_data_empty() -> dict[str, Any]:
    """Fee response with no series."""
    return _make_fee_data([])


@pytest.fixture
def fee_data_no_y() -> dict[str, Any]:
    """Fee response where some data points have no 'y' key."""
    return _make_fee_data(
        [
            _make_series(
                "ConsumptionFee",
                [("2026-02-01", 100.0)],
            )
        ]
    )


# ---------------------------------------------------------------------------
# Config entry / config data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_entry_data_bankid() -> dict[str, Any]:
    return {
        "personnummer": "199001011234",
        "auth_method": "bankid",
        "customer_code": "123456",
        "customer_id": "cust-abc",
        "sub_user_id": "",
        "session_cookies": {},
    }


@pytest.fixture
def config_entry_data_password() -> dict[str, Any]:
    return {
        "personnummer": "199001011234",
        "auth_method": "password",
        "password": "secret",
        "session_cookies": {},
    }
