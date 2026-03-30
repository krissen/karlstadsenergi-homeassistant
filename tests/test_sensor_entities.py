"""Tests for sensor entity classes: WasteCollectionSensor, WasteCollectionSummary,
ElectricityConsumptionSensor, ElectricityPriceSensor, SpotPriceSensor, ContractSensor.

Entities are instantiated directly with mock coordinators.
No HA instance required.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.karlstadsenergi.const import DOMAIN
from custom_components.karlstadsenergi.sensor import (
    ContractSensor,
    ElectricityConsumptionSensor,
    ElectricityPriceSensor,
    SpotPriceSensor,
    WasteCollectionSensor,
    WasteCollectionSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_coord(data: Any) -> MagicMock:
    coord = MagicMock()
    coord.data = data
    return coord


def _make_service(
    service_id: int = 1,
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


def _make_waste_sensor(
    data: Any = None,
    service: dict | None = None,
    customer_id: str = "CUST01",
) -> WasteCollectionSensor:
    coord = _mock_coord(data)
    return WasteCollectionSensor(
        coordinator=coord,
        customer_id=customer_id,
        service=service or _make_service(),
    )


def _make_summary_sensor(
    data: Any = None,
    item: dict | None = None,
    customer_id: str = "CUST01",
) -> WasteCollectionSummary:
    coord = _mock_coord(data)
    return WasteCollectionSummary(
        coordinator=coord,
        customer_id=customer_id,
        item=item
        or {
            "Type": "Mat- och restavfall",
            "Date": "2026-04-15",
            "Address": "Testgatan 1",
            "Size": "140L",
        },
    )


# ---------------------------------------------------------------------------
# WasteCollectionSensor
# ---------------------------------------------------------------------------


class TestWasteCollectionSensor:
    def test_native_value_returns_pickup_date(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        assert sensor.native_value == datetime.date(2026, 4, 15)

    def test_native_value_returns_none_when_no_data(self) -> None:
        sensor = _make_waste_sensor(None)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_service_id_missing(self) -> None:
        data = {"dates": {"999": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        assert sensor.native_value is None

    def test_unique_id_format(self) -> None:
        sensor = _make_waste_sensor()
        expected = f"{DOMAIN}_CUST01_P001_food_and_residual_waste"
        assert sensor.unique_id == expected

    def test_name_is_waste_type(self) -> None:
        sensor = _make_waste_sensor()
        assert sensor._attr_name == "Mat- och restavfall"

    def test_device_info_manufacturer(self) -> None:
        sensor = _make_waste_sensor()
        assert sensor.device_info["manufacturer"] == "Karlstads Energi"

    def test_device_info_identifiers(self) -> None:
        sensor = _make_waste_sensor()
        assert (DOMAIN, "CUST01_P001") in sensor.device_info["identifiers"]

    def test_extra_state_attributes_include_address(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["address"] == "Testgatan 1"

    def test_extra_state_attributes_days_until_pickup(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["days_until_pickup"] == 1

    def test_extra_state_attributes_pickup_is_tomorrow_true(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["pickup_is_tomorrow"] is True

    def test_extra_state_attributes_pickup_is_today_false_when_tomorrow(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["pickup_is_today"] is False

    def test_extra_state_attributes_no_date_keys_when_no_pickup(self) -> None:
        sensor = _make_waste_sensor(None)
        attrs = sensor.extra_state_attributes
        assert "days_until_pickup" not in attrs
        assert "pickup_is_today" not in attrs

    def test_container_size_in_extra_attributes(self) -> None:
        data = {"dates": {"1": "2026-04-15"}}
        sensor = _make_waste_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["container_size"] == "140L"


# ---------------------------------------------------------------------------
# WasteCollectionSummary
# ---------------------------------------------------------------------------


class TestWasteCollectionSummary:
    def test_native_value_returns_date(self) -> None:
        data = {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        sensor = _make_summary_sensor(data)
        assert sensor.native_value == datetime.date(2026, 4, 15)

    def test_native_value_returns_none_when_no_data(self) -> None:
        sensor = _make_summary_sensor(None)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_type_missing(self) -> None:
        data = {"next_dates": [{"Type": "Glas/Metall", "Date": "2026-04-22"}]}
        sensor = _make_summary_sensor(data)
        assert sensor.native_value is None

    def test_unique_id_format(self) -> None:
        sensor = _make_summary_sensor()
        expected = f"{DOMAIN}_CUST01_food_and_residual_waste"
        assert sensor.unique_id == expected

    def test_device_info_identifiers_use_customer_id_only(self) -> None:
        sensor = _make_summary_sensor()
        assert (DOMAIN, "CUST01") in sensor.device_info["identifiers"]

    def test_extra_state_attributes_days_until_pickup(self) -> None:
        data = {"next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-04-15"}]}
        sensor = _make_summary_sensor(data)
        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime.datetime(
                2026, 4, 14, 12, 0, 0, tzinfo=datetime.timezone.utc
            )
            attrs = sensor.extra_state_attributes
        assert attrs["days_until_pickup"] == 1

    def test_address_stripped_in_device_info(self) -> None:
        item = {
            "Type": "Mat- och restavfall",
            "Date": "2026-04-15",
            "Address": "  Testgatan 1  ",
            "Size": "140L",
        }
        sensor = _make_summary_sensor(item=item)
        # address is stripped at construction time
        assert "  " not in sensor.device_info["name"]


# ---------------------------------------------------------------------------
# ElectricityConsumptionSensor
# ---------------------------------------------------------------------------


class TestElectricityConsumptionSensor:
    def _make_sensor(self, data: Any = None) -> ElectricityConsumptionSensor:
        coord = _mock_coord(data)
        return ElectricityConsumptionSensor(coordinator=coord, customer_id="CUST01")

    def test_native_value_returns_cumulative_total(self) -> None:
        """native_value returns cumulative kWh (TOTAL_INCREASING for Energy Dashboard)."""
        data = {
            "consumption": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {
                            "data": [
                                {"dateInterval": "2026-03-01", "y": 120.0},
                                {"dateInterval": "2026-03-02", "y": 135.5},
                            ]
                        }
                    ]
                }
            }
        }
        sensor = self._make_sensor(data)
        # Sum of all data points: 120.0 + 135.5 = 255.5
        assert sensor.native_value == pytest.approx(255.5, abs=0.001)

    def test_native_value_uses_curr_year_value_when_available(self) -> None:
        """CurrYearValue from CompareModel takes precedence over chart sum."""
        data = {
            "consumption": {
                "CompareModel": {"CurrYearValue": 5432.1},
                "DetailedConsumptionChart": {"SeriesList": [{"data": [{"y": 100.0}]}]},
            }
        }
        sensor = self._make_sensor(data)
        assert sensor.native_value == pytest.approx(5432.1, abs=0.001)

    def test_native_value_returns_none_when_no_data(self) -> None:
        sensor = self._make_sensor(None)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_series_list_empty(self) -> None:
        data = {"consumption": {"DetailedConsumptionChart": {"SeriesList": []}}}
        sensor = self._make_sensor(data)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_data_points_empty(self) -> None:
        data = {
            "consumption": {"DetailedConsumptionChart": {"SeriesList": [{"data": []}]}}
        }
        sensor = self._make_sensor(data)
        assert sensor.native_value is None

    def test_native_value_rounded_to_three_decimals(self) -> None:
        data = {
            "consumption": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {"data": [{"dateInterval": "2026-03-01", "y": 123.4567}]}
                    ]
                }
            }
        }
        sensor = self._make_sensor(data)
        val = sensor.native_value
        assert val is not None
        assert val == round(123.4567, 3)

    def test_unique_id_format(self) -> None:
        sensor = self._make_sensor()
        assert sensor.unique_id == f"{DOMAIN}_CUST01_electricity"

    def test_translation_key_is_electricity_consumption(self) -> None:
        sensor = self._make_sensor()
        assert sensor._attr_translation_key == "electricity_consumption"

    def test_extra_state_attributes_monthly_consumption(self) -> None:
        data = {
            "consumption": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {
                            "data": [
                                {"dateInterval": "2026-03-01", "y": 100.0},
                                {"dateInterval": "2026-03-15", "y": 200.0},
                                {"dateInterval": "2026-04-01", "y": 150.0},
                            ]
                        }
                    ]
                },
                "CompareModel": {},
                "ConsumptionModel": {},
            },
            "hourly": {},
            "fee_data": {},
        }
        sensor = self._make_sensor(data)
        attrs = sensor.extra_state_attributes
        monthly = attrs.get("monthly_consumption", {})
        assert monthly.get("2026-03") == pytest.approx(300.0)
        assert monthly.get("2026-04") == pytest.approx(150.0)

    def test_extra_state_attributes_latest_date(self) -> None:
        data = {
            "consumption": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {
                            "data": [
                                {"dateInterval": "2026-03-01", "y": 100.0},
                                {"dateInterval": "2026-03-31", "y": 200.0},
                            ]
                        }
                    ]
                },
                "CompareModel": {},
                "ConsumptionModel": {},
            },
            "hourly": {},
            "fee_data": {},
        }
        sensor = self._make_sensor(data)
        attrs = sensor.extra_state_attributes
        assert attrs.get("latest_date") == "2026-03-31"


# ---------------------------------------------------------------------------
# ElectricityPriceSensor
# ---------------------------------------------------------------------------


class TestElectricityPriceSensor:
    def _make_sensor(self, data: Any = None) -> ElectricityPriceSensor:
        coord = _mock_coord(data)
        return ElectricityPriceSensor(coordinator=coord, customer_id="CUST01")

    def _make_data(
        self,
        consumption_fee: float = 500.0,
        consumption_kwh: float = 250.0,
    ) -> dict[str, Any]:
        return {
            "consumption": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {
                            "data": [
                                {"dateInterval": "2026-03-01", "y": consumption_kwh},
                            ]
                        }
                    ]
                },
                "ConsumptionModel": {},
            },
            "fee_data": {
                "DetailedConsumptionChart": {
                    "SeriesList": [
                        {
                            "id": "ConsumptionFee",
                            "data": [
                                {"dateInterval": "2026-03-01", "y": consumption_fee}
                            ],
                        }
                    ]
                }
            },
        }

    def test_native_value_returns_fee_divided_by_kwh(self) -> None:
        data = self._make_data(consumption_fee=500.0, consumption_kwh=250.0)
        sensor = self._make_sensor(data)
        result = sensor.native_value
        assert result == pytest.approx(2.0, abs=1e-4)

    def test_native_value_returns_none_when_no_data(self) -> None:
        sensor = self._make_sensor(None)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_fee_is_zero(self) -> None:
        data = self._make_data(consumption_fee=0.0, consumption_kwh=100.0)
        sensor = self._make_sensor(data)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_kwh_is_zero(self) -> None:
        data = self._make_data(consumption_fee=500.0, consumption_kwh=0.0)
        sensor = self._make_sensor(data)
        assert sensor.native_value is None

    def test_unique_id_format(self) -> None:
        sensor = self._make_sensor()
        assert sensor.unique_id == f"{DOMAIN}_CUST01_electricity_price"

    def test_extra_state_attributes_contains_fee_breakdown(self) -> None:
        data = self._make_data(consumption_fee=500.0, consumption_kwh=250.0)
        sensor = self._make_sensor(data)
        attrs = sensor.extra_state_attributes
        assert attrs["consumption_fee_sek"] == pytest.approx(500.0)

    def test_extra_state_attributes_total_consumption_kwh(self) -> None:
        data = self._make_data(consumption_fee=500.0, consumption_kwh=250.0)
        sensor = self._make_sensor(data)
        attrs = sensor.extra_state_attributes
        assert attrs["total_consumption_kwh"] == pytest.approx(250.0)

    def test_extra_state_attributes_empty_when_no_data(self) -> None:
        sensor = self._make_sensor(None)
        attrs = sensor.extra_state_attributes
        assert attrs == {}


# ---------------------------------------------------------------------------
# SpotPriceSensor
# ---------------------------------------------------------------------------


class TestSpotPriceSensor:
    def _make_sensor(
        self,
        data: Any = None,
        customer_id: str = "CUST01",
        address: str = "",
        place_id: str = "",
    ) -> SpotPriceSensor:
        coord = _mock_coord(data)
        return SpotPriceSensor(
            coordinator=coord,
            customer_id=customer_id,
            address=address,
            place_id=place_id,
        )

    def test_native_value_returns_current_price(self) -> None:
        sensor = self._make_sensor(
            {"current_price": 1.25, "prices": [], "region": "SE3"}
        )
        assert sensor.native_value == pytest.approx(1.25)

    def test_native_value_returns_none_when_no_data(self) -> None:
        sensor = self._make_sensor(None)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_current_price_none(self) -> None:
        sensor = self._make_sensor(
            {"current_price": None, "prices": [], "region": "SE3"}
        )
        assert sensor.native_value is None

    def test_unique_id_format(self) -> None:
        sensor = self._make_sensor()
        assert sensor.unique_id == f"{DOMAIN}_CUST01_spot_price"

    def test_extra_state_attributes_empty_when_no_data(self) -> None:
        sensor = self._make_sensor(None)
        assert sensor.extra_state_attributes == {}

    def test_extra_state_attributes_region(self) -> None:
        sensor = self._make_sensor(
            {"current_price": 1.25, "prices": [], "region": "SE3"}
        )
        attrs = sensor.extra_state_attributes
        assert attrs["region"] == "SE3"

    def test_extra_state_attributes_price_ore_kwh(self) -> None:
        sensor = self._make_sensor(
            {"current_price": 1.0, "prices": [], "region": "SE3"}
        )
        attrs = sensor.extra_state_attributes
        assert attrs["price_ore_kwh"] == pytest.approx(100.0)

    def test_extra_state_attributes_no_price_ore_when_none(self) -> None:
        sensor = self._make_sensor(
            {"current_price": None, "prices": [], "region": "SE3"}
        )
        attrs = sensor.extra_state_attributes
        assert "price_ore_kwh" not in attrs

    def test_device_info_uses_place_id_when_present(self) -> None:
        sensor = self._make_sensor(address="Testgatan 1", place_id="P99")
        identifiers = sensor.device_info["identifiers"]
        assert (DOMAIN, "CUST01_P99") in identifiers

    def test_device_info_uses_customer_id_only_when_no_place_id(self) -> None:
        sensor = self._make_sensor()
        identifiers = sensor.device_info["identifiers"]
        assert (DOMAIN, "CUST01") in identifiers

    def test_extra_state_attributes_today_min_max_avg(self) -> None:
        from datetime import datetime, timezone, timedelta

        # Build prices for today (UTC)
        today_utc = datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)
        prices = [
            {"start": today_utc, "price_sek": 1.0, "price_ore": 100.0},
            {
                "start": today_utc + timedelta(hours=1),
                "price_sek": 2.0,
                "price_ore": 200.0,
            },
        ]
        data = {"current_price": 1.5, "prices": prices, "region": "SE3"}
        sensor = self._make_sensor(data)

        with patch("custom_components.karlstadsenergi.sensor.dt_util") as mock_dt:
            mock_now = datetime(2026, 4, 14, 11, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            attrs = sensor.extra_state_attributes

        assert attrs["today_min"] == pytest.approx(1.0)
        assert attrs["today_max"] == pytest.approx(2.0)
        assert attrs["today_average"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# ContractSensor
# ---------------------------------------------------------------------------


class TestContractSensor:
    def _make_contract(
        self,
        contract_id: str = "C001",
        utility_name: str = "Elnät - Nätavtal",
        alternative: str = "Fast nätpris",
    ) -> dict[str, Any]:
        return {
            "ContractId": contract_id,
            "UtilityName": utility_name,
            "ContractAlternative": alternative,
            "ContractStartDate": "2025-01-01",
            "ContractEndDate": "2026-01-01",
            "NetAreaCode": "SE3",
            "ElecticityRegion": "SE3",
        }

    def _make_sensor(
        self,
        contracts: list[dict] | None = None,
        contract: dict | None = None,
    ) -> ContractSensor:
        contract = contract or self._make_contract()
        data = {"contracts": contracts if contracts is not None else [contract]}
        coord = _mock_coord(data)
        return ContractSensor(
            coordinator=coord,
            customer_id="CUST01",
            contract=contract,
        )

    def test_native_value_returns_contract_alternative(self) -> None:
        sensor = self._make_sensor()
        assert sensor.native_value == "Fast nätpris"

    def test_native_value_falls_back_to_utility_name(self) -> None:
        contract = self._make_contract(alternative="")
        sensor = self._make_sensor(contract=contract)
        assert sensor.native_value == "Elnät - Nätavtal"

    def test_native_value_returns_none_when_no_data(self) -> None:
        coord = _mock_coord(None)
        contract = self._make_contract()
        sensor = ContractSensor(
            coordinator=coord,
            customer_id="CUST01",
            contract=contract,
        )
        assert sensor.native_value is None

    def test_native_value_returns_none_when_contract_id_missing(self) -> None:
        # Contract with different ID than what's in coordinator data
        contract = self._make_contract(contract_id="C001")
        other = self._make_contract(contract_id="C999")
        data = {"contracts": [other]}
        coord = _mock_coord(data)
        sensor = ContractSensor(
            coordinator=coord, customer_id="CUST01", contract=contract
        )
        assert sensor.native_value is None

    def test_unique_id_format(self) -> None:
        sensor = self._make_sensor()
        assert sensor.unique_id == f"{DOMAIN}_CUST01_contract_C001"

    def test_translation_key_and_placeholders(self) -> None:
        sensor = self._make_sensor()
        assert sensor._attr_translation_key == "contract"
        assert (
            sensor._attr_translation_placeholders["utility_name"] == "Elnät - Nätavtal"
        )

    def test_extra_state_attributes_present(self) -> None:
        sensor = self._make_sensor()
        attrs = sensor.extra_state_attributes
        assert attrs["contract_id"] == "C001"
        assert attrs["utility_name"] == "Elnät - Nätavtal"
        assert attrs["contract_start_date"] == "2025-01-01"
        assert attrs["contract_end_date"] == "2026-01-01"

    def test_extra_state_attributes_empty_when_no_data(self) -> None:
        coord = _mock_coord(None)
        contract = self._make_contract()
        sensor = ContractSensor(
            coordinator=coord, customer_id="CUST01", contract=contract
        )
        assert sensor.extra_state_attributes == {}

    def test_extra_state_attributes_does_not_contain_gsrn_number(self) -> None:
        """GsrnNumber is PII and must not appear in entity attributes."""
        contract = {**self._make_contract(), "GsrnNumber": "735999999000000001"}
        sensor = self._make_sensor(contract=contract, contracts=[contract])
        attrs = sensor.extra_state_attributes
        assert "GsrnNumber" not in attrs
        assert "gsrn_number" not in attrs

    def test_device_info_manufacturer(self) -> None:
        sensor = self._make_sensor()
        assert sensor.device_info["manufacturer"] == "Karlstads Energi"
