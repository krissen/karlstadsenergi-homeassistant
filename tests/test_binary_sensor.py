"""Tests for WastePickupTomorrowSensor and WastePickupTomorrowSummarySensor.

Entities are instantiated directly with mock coordinators.
dt_util.now() is patched for deterministic date comparisons.
No HA instance required.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock, patch


from custom_components.karlstadsenergi.binary_sensor import (
    WastePickupTomorrowSensor,
    WastePickupTomorrowSummarySensor,
)
from custom_components.karlstadsenergi.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# "Today" as seen by the mocked dt_util.now()
_TODAY = datetime.datetime(2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc)
_TOMORROW_DATE = datetime.date(2026, 4, 15)
_TODAY_DATE = datetime.date(2026, 4, 14)
_YESTERDAY_DATE = datetime.date(2026, 4, 13)


def _mock_coordinator(data: Any) -> MagicMock:
    coord = MagicMock()
    coord.data = data
    return coord


def _make_service(
    service_id: int = 123,
    waste_type: str = "Mat- och restavfall",
    address: str = "Testgatan 1",
    place_id: str = "P001",
) -> dict[str, Any]:
    return {
        "FlexServiceId": service_id,
        "FlexServiceContainTypeValue": waste_type,
        "FlexServicePlaceAddress": address,
        "FlexServicePlaceId": place_id,
        "FetchFrequency": "Varannan vecka",
        "SizeOfFlexIndividual": "140L",
    }


def _make_detailed_sensor(
    coord: MagicMock,
    customer_id: str = "CUST01",
    service: dict[str, Any] | None = None,
) -> WastePickupTomorrowSensor:
    return WastePickupTomorrowSensor(
        coordinator=coord,
        customer_id=customer_id,
        service=service or _make_service(),
    )


def _make_summary_item(
    waste_type: str = "Mat- och restavfall",
    date: str = "2026-04-15",
    address: str = "Testgatan 1",
) -> dict[str, Any]:
    return {"Type": waste_type, "Date": date, "Address": address, "Size": "140L"}


def _make_summary_sensor(
    coord: MagicMock,
    customer_id: str = "CUST01",
    item: dict[str, Any] | None = None,
) -> WastePickupTomorrowSummarySensor:
    return WastePickupTomorrowSummarySensor(
        coordinator=coord,
        customer_id=customer_id,
        item=item or _make_summary_item(),
    )


# ---------------------------------------------------------------------------
# WastePickupTomorrowSensor -- is_on
# ---------------------------------------------------------------------------


class TestDetailedIsOn:
    def test_is_on_true_when_pickup_is_tomorrow(self) -> None:
        coord = _mock_coordinator({"dates": {"123": _TOMORROW_DATE.isoformat()}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is True

    def test_is_on_false_when_pickup_is_today(self) -> None:
        coord = _mock_coordinator({"dates": {"123": _TODAY_DATE.isoformat()}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is False

    def test_is_on_false_when_pickup_is_yesterday(self) -> None:
        coord = _mock_coordinator({"dates": {"123": _YESTERDAY_DATE.isoformat()}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is False

    def test_is_on_false_when_pickup_is_two_days_away(self) -> None:
        two_days = (_TODAY_DATE + datetime.timedelta(days=2)).isoformat()
        coord = _mock_coordinator({"dates": {"123": two_days}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is False

    def test_is_on_none_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        assert sensor.is_on is None

    def test_is_on_none_when_service_id_missing_from_dates(self) -> None:
        coord = _mock_coordinator({"dates": {"999": "2026-04-15"}})
        sensor = _make_detailed_sensor(coord)
        assert sensor.is_on is None

    def test_is_on_none_when_date_is_invalid(self) -> None:
        coord = _mock_coordinator({"dates": {"123": "not-a-date"}})
        sensor = _make_detailed_sensor(coord)
        assert sensor.is_on is None


# ---------------------------------------------------------------------------
# WastePickupTomorrowSensor -- icon
# ---------------------------------------------------------------------------


class TestDetailedIcon:
    def test_icon_is_trash_can_when_on(self) -> None:
        coord = _mock_coordinator({"dates": {"123": _TOMORROW_DATE.isoformat()}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.icon == "mdi:trash-can"

    def test_icon_is_trash_can_outline_when_off(self) -> None:
        coord = _mock_coordinator({"dates": {"123": _TODAY_DATE.isoformat()}})
        sensor = _make_detailed_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.icon == "mdi:trash-can-outline"

    def test_icon_is_trash_can_outline_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        # is_on returns None -> falsy -> outline
        assert sensor.icon == "mdi:trash-can-outline"


# ---------------------------------------------------------------------------
# WastePickupTomorrowSensor -- unique_id and device_info
# ---------------------------------------------------------------------------


class TestDetailedIdentifiers:
    def test_unique_id_format(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        expected = f"{DOMAIN}_CUST01_P001_food_and_residual_waste_pickup_tomorrow"
        assert sensor.unique_id == expected

    def test_unique_id_contains_place_id(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        assert "P001" in sensor.unique_id

    def test_unique_id_contains_customer_id(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord, customer_id="CUST01")
        assert "CUST01" in sensor.unique_id

    def test_unique_id_ends_with_pickup_tomorrow(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        assert sensor.unique_id.endswith("_pickup_tomorrow")

    def test_device_info_identifiers(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        identifiers = sensor.device_info["identifiers"]
        assert (DOMAIN, "CUST01_P001") in identifiers

    def test_device_info_name_contains_address(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        assert "Testgatan 1" in sensor.device_info["name"]

    def test_device_info_manufacturer(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_detailed_sensor(coord)
        assert sensor.device_info["manufacturer"] == "Karlstads Energi"


# ---------------------------------------------------------------------------
# WastePickupTomorrowSummarySensor -- is_on
# ---------------------------------------------------------------------------


class TestSummaryIsOn:
    def test_is_on_true_when_pickup_is_tomorrow(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        )
        sensor = _make_summary_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is True

    def test_is_on_false_when_pickup_is_today(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-14"}]}
        )
        sensor = _make_summary_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is False

    def test_is_on_false_when_pickup_is_next_week(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-21"}]}
        )
        sensor = _make_summary_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.is_on is False

    def test_is_on_none_when_no_data(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert sensor.is_on is None

    def test_is_on_none_when_type_not_found_in_next_dates(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Glas/Metall", "Date": "2026-04-15"}]}
        )
        sensor = _make_summary_sensor(coord)
        assert sensor.is_on is None

    def test_is_on_none_for_invalid_date_string(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "bad-date"}]}
        )
        sensor = _make_summary_sensor(coord)
        assert sensor.is_on is None

    def test_matches_correct_type_when_multiple_present(self) -> None:
        """Must match on Type, not just return first entry's date."""
        item = _make_summary_item(waste_type="Glas/Metall", date="2026-04-22")
        coord = _mock_coordinator(
            {
                "next_dates": [
                    {"Type": "Mat- och restavfall", "Date": "2026-04-15"},
                    {"Type": "Glas/Metall", "Date": "2026-04-22"},
                ]
            }
        )
        sensor = _make_summary_sensor(coord, item=item)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            # "today" is 2026-04-21, so Glas/Metall (2026-04-22) is tomorrow
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 21, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            assert sensor.is_on is True


# ---------------------------------------------------------------------------
# WastePickupTomorrowSummarySensor -- icon
# ---------------------------------------------------------------------------


class TestSummaryIcon:
    def test_icon_trash_can_when_on(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        )
        sensor = _make_summary_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.icon == "mdi:trash-can"

    def test_icon_trash_can_outline_when_off(self) -> None:
        coord = _mock_coordinator(
            {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-05-01"}]}
        )
        sensor = _make_summary_sensor(coord)
        with patch(
            "custom_components.karlstadsenergi.binary_sensor.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _TODAY
            assert sensor.icon == "mdi:trash-can-outline"

    def test_icon_trash_can_outline_when_none(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert sensor.icon == "mdi:trash-can-outline"


# ---------------------------------------------------------------------------
# WastePickupTomorrowSummarySensor -- unique_id and device_info
# ---------------------------------------------------------------------------


class TestSummaryIdentifiers:
    def test_unique_id_format(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        expected = f"{DOMAIN}_CUST01_food_and_residual_waste_pickup_tomorrow"
        assert sensor.unique_id == expected

    def test_unique_id_contains_customer_id(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord, customer_id="CUST01")
        assert "CUST01" in sensor.unique_id

    def test_unique_id_contains_slug(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert "food_and_residual_waste" in sensor.unique_id

    def test_unique_id_ends_with_pickup_tomorrow(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert sensor.unique_id.endswith("_pickup_tomorrow")

    def test_unique_id_does_not_contain_place_id(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert "P001" not in sensor.unique_id

    def test_device_info_identifiers_use_customer_id_only(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        identifiers = sensor.device_info["identifiers"]
        assert (DOMAIN, "CUST01") in identifiers

    def test_device_info_name_contains_address(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert "Testgatan 1" in sensor.device_info["name"]

    def test_device_info_manufacturer(self) -> None:
        coord = _mock_coordinator(None)
        sensor = _make_summary_sensor(coord)
        assert sensor.device_info["manufacturer"] == "Karlstads Energi"
