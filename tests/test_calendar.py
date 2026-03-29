"""Tests for WasteCollectionCalendar and WasteCollectionSummaryCalendar.

Entities are instantiated directly with mock coordinators.
No HA instance required.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.karlstadsenergi.calendar import (
    WasteCollectionCalendar,
    WasteCollectionSummaryCalendar,
)
from custom_components.karlstadsenergi.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_coordinator(data: Any) -> MagicMock:
    """Return a minimal coordinator mock with .data set."""
    coord = MagicMock()
    coord.data = data
    return coord


def _make_service(
    service_id: int = 123,
    waste_type: str = "Mat- och restavfall",
    address: str = "Testgatan 1",
    frequency: str = "Varannan vecka",
    place_id: str = "P001",
    size: str = "140L",
) -> dict[str, Any]:
    return {
        "FlexServiceId": service_id,
        "FlexServiceContainTypeValue": waste_type,
        "FlexServicePlaceAddress": address,
        "FetchFrequency": frequency,
        "FlexServicePlaceId": place_id,
        "SizeOfFlexIndividual": size,
    }


def _make_detailed_calendar(
    coord: MagicMock,
    customer_id: str = "CUST01",
    service: dict[str, Any] | None = None,
) -> WasteCollectionCalendar:
    return WasteCollectionCalendar(
        coordinator=coord,
        customer_id=customer_id,
        service=service or _make_service(),
    )


def _make_summary_item(
    waste_type: str = "Mat- och restavfall",
    date: str = "2026-04-15",
    address: str = "Testgatan 1",
    size: str = "140L",
) -> dict[str, Any]:
    return {"Type": waste_type, "Date": date, "Address": address, "Size": size}


def _make_summary_calendar(
    coord: MagicMock,
    customer_id: str = "CUST01",
    item: dict[str, Any] | None = None,
) -> WasteCollectionSummaryCalendar:
    return WasteCollectionSummaryCalendar(
        coordinator=coord,
        customer_id=customer_id,
        item=item or _make_summary_item(),
    )


# ---------------------------------------------------------------------------
# WasteCollectionCalendar -- _next_pickup_date
# ---------------------------------------------------------------------------


class TestDetailedNextPickupDate:
    """Test date lookup via the event property (date logic in const helpers)."""

    def test_returns_correct_date_from_coordinator(self) -> None:
        coord = _mock_coordinator(
            {"dates": {"123": "2026-04-15"}, "services": [_make_service()]}
        )
        cal = _make_detailed_calendar(coord)
        assert cal.event is not None
        assert cal.event.start == datetime.date(2026, 4, 15)

    def test_returns_none_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_returns_none_when_data_is_empty_dict(self) -> None:
        coord = _mock_coordinator({})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_returns_none_when_service_id_not_in_dates(self) -> None:
        coord = _mock_coordinator({"dates": {"999": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_returns_none_for_invalid_date_string(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "not-a-date"}})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_returns_none_for_empty_date_string(self) -> None:
        coord = _mock_coordinator({"dates": {"123": ""}})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_returns_none_for_none_date_value(self) -> None:
        coord = _mock_coordinator({"dates": {"123": None}})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None


# ---------------------------------------------------------------------------
# WasteCollectionCalendar -- event property
# ---------------------------------------------------------------------------


class TestDetailedEventProperty:
    def test_event_has_correct_summary_with_frequency(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        event = cal.event
        assert event is not None
        assert event.summary == "Mat- och restavfall (Varannan vecka)"

    def test_event_has_correct_start_date(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        event = cal.event
        assert event is not None
        assert event.start == datetime.date(2026, 4, 15)

    def test_event_end_is_day_after_start(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        event = cal.event
        assert event is not None
        assert event.end == datetime.date(2026, 4, 16)

    def test_event_summary_without_frequency(self) -> None:
        """When frequency is empty, summary is just the waste type."""
        service = _make_service(frequency="")
        coord = _mock_coordinator({"dates": {"123": "2026-04-15"}})
        cal = _make_detailed_calendar(coord, service=service)
        event = cal.event
        assert event is not None
        assert event.summary == "Mat- och restavfall"

    def test_event_returns_none_when_no_pickup_date(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert cal.event is None

    def test_event_returns_none_when_no_matching_service_id(self) -> None:
        coord = _mock_coordinator({"dates": {"999": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        assert cal.event is None


# ---------------------------------------------------------------------------
# WasteCollectionCalendar -- async_get_events
# ---------------------------------------------------------------------------


class TestDetailedAsyncGetEvents:
    @pytest.mark.asyncio
    async def test_returns_event_within_date_range(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-04-15"}})
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert len(events) == 1
        assert events[0].start == datetime.date(2026, 4, 15)

    @pytest.mark.asyncio
    async def test_returns_empty_when_pickup_before_range(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-03-10"}})
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_pickup_after_range(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "2026-05-01"}})
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []

    @pytest.mark.asyncio
    async def test_pickup_on_range_start_is_included(self) -> None:
        """Pickup on start date must be included (start <= pickup < end)."""
        coord = _mock_coordinator({"dates": {"123": "2026-04-01"}})
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_pickup_on_range_end_is_excluded(self) -> None:
        """Pickup on end date is excluded (strict less-than)."""
        coord = _mock_coordinator({"dates": {"123": "2026-04-30"}})
        cal = _make_detailed_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []


# ---------------------------------------------------------------------------
# WasteCollectionCalendar -- unique_id and device_info
# ---------------------------------------------------------------------------


class TestDetailedIdentifiers:
    def test_unique_id_contains_place_id(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert "P001" in cal.unique_id

    def test_unique_id_contains_customer_id(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord, customer_id="CUST01")
        assert "CUST01" in cal.unique_id

    def test_unique_id_contains_slug(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        # "Mat- och restavfall" -> "food_and_residual_waste"
        assert "food_and_residual_waste" in cal.unique_id

    def test_unique_id_ends_with_calendar(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert cal.unique_id.endswith("_calendar")

    def test_unique_id_format(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        expected = f"{DOMAIN}_CUST01_P001_food_and_residual_waste_calendar"
        assert cal.unique_id == expected

    def test_device_info_identifiers_contain_place_id(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        identifiers = cal.device_info["identifiers"]
        assert (DOMAIN, "CUST01_P001") in identifiers

    def test_device_info_name_contains_address(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert "Testgatan 1" in cal.device_info["name"]

    def test_device_info_manufacturer(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_detailed_calendar(coord)
        assert cal.device_info["manufacturer"] == "Karlstads Energi"


# ---------------------------------------------------------------------------
# WasteCollectionSummaryCalendar -- _next_pickup_date
# ---------------------------------------------------------------------------


class TestSummaryNextPickupDate:
    """Test date lookup via the event property (date logic in const helpers)."""

    def test_returns_correct_date_from_coordinator(self) -> None:
        coord = _mock_coordinator(
            {
                "next_dates": [
                    {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
                    {"Type": "Glas/Metall", "Date": "2026-04-22"},
                ]
            }
        )
        cal = _make_summary_calendar(coord)
        assert cal.event is not None
        assert cal.event.start == datetime.date(2026, 4, 15)

    def test_returns_none_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert cal.event is None

    def test_returns_none_when_type_not_found(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Glas/Metall", "Date": "2026-04-22"}]}
        )
        cal = _make_summary_calendar(coord)
        assert cal.event is None

    def test_returns_none_for_invalid_date_string(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "bad-date"}]}
        )
        cal = _make_summary_calendar(coord)
        assert cal.event is None

    def test_returns_none_when_date_key_missing(self) -> None:
        coord = _mock_coordinator({"next_dates": [{"Type": "Mat- och restavfall"}]})
        cal = _make_summary_calendar(coord)
        assert cal.event is None

    def test_returns_none_when_next_dates_empty(self) -> None:
        coord = _mock_coordinator({"next_dates": []})
        cal = _make_summary_calendar(coord)
        assert cal.event is None

    def test_returns_correct_type_when_multiple_present(self) -> None:
        """Summary calendar must match on Type, not just return the first entry."""
        item = _make_summary_item(waste_type="Glas/Metall", date="2026-04-22")
        coord = _mock_coordinator(
            {
                "next_dates": [
                    {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
                    {"Type": "Glas/Metall", "Date": "2026-04-22"},
                ]
            }
        )
        cal = _make_summary_calendar(coord, item=item)
        assert cal.event is not None
        assert cal.event.start == datetime.date(2026, 4, 22)


# ---------------------------------------------------------------------------
# WasteCollectionSummaryCalendar -- event property
# ---------------------------------------------------------------------------


class TestSummaryEventProperty:
    def test_event_has_correct_summary(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        )
        cal = _make_summary_calendar(coord)
        event = cal.event
        assert event is not None
        assert event.summary == "Mat- och restavfall"

    def test_event_start_and_end_dates(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        )
        cal = _make_summary_calendar(coord)
        event = cal.event
        assert event is not None
        assert event.start == datetime.date(2026, 4, 15)
        assert event.end == datetime.date(2026, 4, 16)

    def test_event_returns_none_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert cal.event is None


# ---------------------------------------------------------------------------
# WasteCollectionSummaryCalendar -- async_get_events
# ---------------------------------------------------------------------------


class TestSummaryAsyncGetEvents:
    @pytest.mark.asyncio
    async def test_returns_event_within_date_range(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        )
        cal = _make_summary_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert len(events) == 1
        assert events[0].start == datetime.date(2026, 4, 15)

    @pytest.mark.asyncio
    async def test_returns_empty_when_pickup_outside_range(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-05-10"}]}
        )
        cal = _make_summary_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        start = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)
        events = await cal.async_get_events(MagicMock(), start, end)
        assert events == []


# ---------------------------------------------------------------------------
# WasteCollectionSummaryCalendar -- unique_id and device_info
# ---------------------------------------------------------------------------


class TestSummaryIdentifiers:
    def test_unique_id_contains_customer_id(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord, customer_id="CUST01")
        assert "CUST01" in cal.unique_id

    def test_unique_id_contains_slug(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert "food_and_residual_waste" in cal.unique_id

    def test_unique_id_ends_with_calendar(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert cal.unique_id.endswith("_calendar")

    def test_unique_id_format(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        expected = f"{DOMAIN}_CUST01_food_and_residual_waste_calendar"
        assert cal.unique_id == expected

    def test_unique_id_does_not_contain_place_id(self) -> None:
        """Summary mode has no place_id -- confirm it is absent."""
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert "P001" not in cal.unique_id

    def test_device_info_identifiers_use_customer_id_only(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        identifiers = cal.device_info["identifiers"]
        assert (DOMAIN, "CUST01") in identifiers

    def test_device_info_name_contains_address(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert "Testgatan 1" in cal.device_info["name"]

    def test_device_info_manufacturer(self) -> None:
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord)
        assert cal.device_info["manufacturer"] == "Karlstads Energi"

    def test_address_is_stripped_of_whitespace(self) -> None:
        """Address from item should be stripped before use in device_info."""
        item = _make_summary_item(address="  Testgatan 1  ")
        coord = _mock_coordinator(None)
        cal = _make_summary_calendar(coord, item=item)
        assert "  " not in cal.device_info["name"]
