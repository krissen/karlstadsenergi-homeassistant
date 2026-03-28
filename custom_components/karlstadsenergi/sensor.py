"""Sensor platform for Karlstadsenergi."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import (
    KarlstadsenergiConsumptionCoordinator,
    KarlstadsenergiContractCoordinator,
    KarlstadsenergiSpotPriceCoordinator,
    KarlstadsenergiWasteCoordinator,
)
from .const import (
    CONF_PERSONNUMMER,
    CONTRACT_TYPE_SLUG,
    DOMAIN,
    FEE_CONSUMPTION,
    FEE_ENERGY_TAX,
    FEE_FIXED,
    FEE_POWER,
    FEE_SUM,
    FEE_VAT,
    WASTE_TYPE_SLUG,
)


def _slug_for_waste_type(waste_type: str) -> str:
    """Get English slug for a Swedish waste type name."""
    slug = WASTE_TYPE_SLUG.get(waste_type)
    if slug:
        return slug
    # Fallback: lowercase, replace non-alphanumeric with underscore
    return "".join(c if c.isalnum() else "_" for c in waste_type.lower()).strip("_")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Karlstadsenergi sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    waste_coordinator: KarlstadsenergiWasteCoordinator = data["waste_coordinator"]
    consumption_coordinator: KarlstadsenergiConsumptionCoordinator = data[
        "consumption_coordinator"
    ]
    customer_number = entry.data[CONF_PERSONNUMMER]

    entities: list[SensorEntity] = []

    # Waste collection sensors
    if waste_coordinator.data:
        services = waste_coordinator.data.get("services", [])
        next_dates = waste_coordinator.data.get("next_dates", [])

        if services:
            # Detailed mode: one sensor per service
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                entities.append(
                    WasteCollectionSensor(
                        coordinator=waste_coordinator,
                        customer_number=customer_number,
                        service=service,
                    )
                )
        elif next_dates:
            # Summary mode: create sensors from start page data
            for item in next_dates:
                waste_type = item.get("Type", "")
                if not waste_type:
                    continue
                entities.append(
                    WasteCollectionSummary(
                        coordinator=waste_coordinator,
                        customer_number=customer_number,
                        item=item,
                    )
                )

    # Electricity consumption sensor
    if consumption_coordinator.data:
        consumption = consumption_coordinator.data.get("consumption", {})
        model = consumption.get("ConsumptionModel", {})
        if model:
            entities.append(
                ElectricityConsumptionSensor(
                    coordinator=consumption_coordinator,
                    customer_number=customer_number,
                )
            )

        # Electricity price sensor (from fee breakdown)
        fee_data = consumption_coordinator.data.get("fee_data", {})
        if fee_data:
            entities.append(
                ElectricityPriceSensor(
                    coordinator=consumption_coordinator,
                    customer_number=customer_number,
                )
            )

    # Spot price sensor (public Evado API)
    spot_price_coordinator: KarlstadsenergiSpotPriceCoordinator = data[
        "spot_price_coordinator"
    ]
    if (
        spot_price_coordinator.data
        and spot_price_coordinator.data.get("current_price") is not None
    ):
        entities.append(
            SpotPriceSensor(
                coordinator=spot_price_coordinator,
                customer_number=customer_number,
            )
        )

    # Contract sensors (one per contract)
    contract_coordinator: KarlstadsenergiContractCoordinator = data[
        "contract_coordinator"
    ]
    if contract_coordinator.data:
        for contract in contract_coordinator.data.get("contracts", []):
            utility = contract.get("UtilityName", "")
            if utility:
                entities.append(
                    ContractSensor(
                        coordinator=contract_coordinator,
                        customer_number=customer_number,
                        contract=contract,
                    )
                )

    async_add_entities(entities, update_before_add=False)


class WasteCollectionSensor(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    SensorEntity,
):
    """Sensor for waste collection next pickup date."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:trash-can"

    def __init__(
        self,
        coordinator: KarlstadsenergiWasteCoordinator,
        customer_number: str,
        service: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._service_id = service["FlexServiceId"]
        self._waste_type = service.get("FlexServiceContainTypeValue", "")
        self._slug = _slug_for_waste_type(self._waste_type)
        self._address = service.get("FlexServicePlaceAddress", "")
        self._container_size = service.get("SizeOfFlexIndividual", "")
        self._frequency = service.get("FetchFrequency", "")
        self._place_id = service.get("FlexServicePlaceId", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_number}_{self._slug}"
        self._attr_name = self._waste_type
        self._attr_translation_key = self._slug

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}_{self._place_id}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
        )

    @property
    def native_value(self) -> datetime.date | None:
        """Return next pickup date."""
        if not self.coordinator.data:
            return None
        dates = self.coordinator.data.get("dates", {})
        date_str = dates.get(str(self._service_id))
        if not date_str:
            return None
        try:
            return datetime.date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "address": self._address,
            "container_size": self._container_size,
            "frequency": self._frequency,
            "service_id": self._service_id,
        }
        pickup_date = self.native_value
        if pickup_date:
            today = datetime.date.today()
            delta = (pickup_date - today).days
            attrs["days_until_pickup"] = delta
            attrs["pickup_is_today"] = delta == 0
            attrs["pickup_is_tomorrow"] = delta == 1
        return attrs


class WasteCollectionSummary(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    SensorEntity,
):
    """Sensor for waste collection from start page summary data."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:trash-can"

    def __init__(
        self,
        coordinator: KarlstadsenergiWasteCoordinator,
        customer_number: str,
        item: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._waste_type = item.get("Type", "")
        self._slug = _slug_for_waste_type(self._waste_type)
        self._address = item.get("Address", "").strip()
        self._container_size = item.get("Size", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_number}_{self._slug}"
        self._attr_name = self._waste_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
        )

    @property
    def native_value(self) -> datetime.date | None:
        if not self.coordinator.data:
            return None
        for item in self.coordinator.data.get("next_dates", []):
            if item.get("Type") == self._waste_type:
                try:
                    return datetime.date.fromisoformat(item["Date"])
                except (ValueError, TypeError, KeyError):
                    return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "address": self._address,
            "container_size": self._container_size,
        }
        pickup_date = self.native_value
        if pickup_date:
            today = datetime.date.today()
            delta = (pickup_date - today).days
            attrs["days_until_pickup"] = delta
            attrs["pickup_is_today"] = delta == 0
            attrs["pickup_is_tomorrow"] = delta == 1
        return attrs


class ElectricityConsumptionSensor(
    CoordinatorEntity[KarlstadsenergiConsumptionCoordinator],
    SensorEntity,
):
    """Sensor for electricity consumption."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:flash"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_number: str,
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._attr_unique_id = f"{DOMAIN}_{customer_number}_electricity"
        self._attr_name = "Electricity consumption"

    @property
    def device_info(self) -> DeviceInfo:
        address = self._get_address()
        place_id = self._get_site_id()
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}_{place_id}")},
            name=f"Karlstadsenergi ({address})",
            manufacturer="Karlstads Energi",
        )

    def _get_model(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        consumption = self.coordinator.data.get("consumption", {})
        return consumption.get("ConsumptionModel", {})

    def _get_address(self) -> str:
        model = self._get_model()
        return model.get("SiteName", "")

    def _get_site_id(self) -> str:
        model = self._get_model()
        return model.get("SiteId", "")

    @property
    def native_value(self) -> float | None:
        """Return latest day's consumption in kWh."""
        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if not series_list:
            return None
        series = series_list[0]
        data_points = series.get("data", [])
        if not data_points:
            return None
        # Return the last data point's value
        last = data_points[-1]
        value = last.get("y")
        if value is not None:
            return round(float(value), 3)
        return None

    @property
    def last_reset(self) -> datetime.datetime | None:
        """Return the start of the day the consumption value corresponds to."""
        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if not series_list:
            return None
        data_points = series_list[0].get("data", [])
        if not data_points:
            return None
        date_str = data_points[-1].get("dateInterval", "")
        if not date_str:
            return None
        try:
            naive_date = datetime.date.fromisoformat(date_str[:10])
            midnight = datetime.datetime.combine(
                naive_date,
                datetime.time.min,
            )
            return midnight.replace(tzinfo=dt_util.get_default_time_zone())
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}

        # Service info
        service_info = (
            self.coordinator.data.get("service_info", {})
            if self.coordinator.data
            else {}
        )
        if service_info:
            attrs["meter_number"] = service_info.get("MeterNumber", "")
            attrs["service_identifier"] = service_info.get(
                "ServiceIdentifier",
                "",
            )
            attrs["net_area"] = service_info.get("NetAreaId", "")

        # Comparison data
        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )
        compare = consumption.get("CompareModel", {})
        if compare:
            attrs["total_this_period"] = compare.get("CurrYearValue")
            attrs["total_last_year_period"] = compare.get("LastYearValue")
            attrs["difference_percentage"] = compare.get(
                "DifferencePercentage",
            )
            attrs["average_daily"] = compare.get("CurrYearAvg")
            attrs["average_daily_last_year"] = compare.get("LastYearAvg")

        # Monthly breakdown from chart data
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if series_list:
            data_points = series_list[0].get("data", [])
            # Group by month
            monthly: dict[str, float] = {}
            for point in data_points:
                date_str = point.get("dateInterval", "")
                value = point.get("y", 0)
                if date_str and value:
                    month_key = date_str[:7]  # "2026-03"
                    monthly[month_key] = monthly.get(month_key, 0) + value
            if monthly:
                attrs["monthly_consumption"] = {
                    k: round(v, 1) for k, v in monthly.items()
                }

            # Latest date
            if data_points:
                attrs["latest_date"] = data_points[-1].get(
                    "dateInterval",
                    "",
                )

        # Hourly data (last 24h for today)
        hourly = (
            self.coordinator.data.get("hourly", {}) if self.coordinator.data else {}
        )
        hourly_chart = hourly.get("DetailedConsumptionChart", {})
        hourly_series = hourly_chart.get("SeriesList", [])
        if hourly_series:
            hourly_points = hourly_series[0].get("data", [])
            # Last 24 points
            recent = hourly_points[-24:] if len(hourly_points) >= 24 else hourly_points
            attrs["hourly_consumption"] = [
                {"time": p.get("dateInterval", ""), "kWh": p.get("y", 0)}
                for p in recent
            ]
            attrs["hourly_data_points"] = len(hourly_points)

        return attrs


def _extract_fee_series(fee_data: dict) -> dict[str, float]:
    """Extract fee amounts from fee-type consumption response.

    Returns dict of series_id -> total SEK for the period.
    """
    chart = fee_data.get("DetailedConsumptionChart", {})
    series_list = chart.get("SeriesList", [])
    fees: dict[str, float] = {}
    for series in series_list:
        series_id = series.get("id", "")
        if not series_id:
            continue
        data_points = series.get("data", [])
        total = sum(p.get("y", 0) for p in data_points)
        fees[series_id] = round(total, 2)
    return fees


def _slug_for_contract(utility_name: str) -> str:
    """Get English slug for a Swedish contract utility name."""
    slug = CONTRACT_TYPE_SLUG.get(utility_name)
    if slug:
        return slug
    return "".join(c if c.isalnum() else "_" for c in utility_name.lower()).strip("_")


class ElectricityPriceSensor(
    CoordinatorEntity[KarlstadsenergiConsumptionCoordinator],
    SensorEntity,
):
    """Effective electricity price derived from fee breakdown.

    Compatible with HA Energy Dashboard (matches Nordpool/Tibber pattern).
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "SEK/kWh"
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_number: str,
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._attr_unique_id = f"{DOMAIN}_{customer_number}_electricity_price"
        self._attr_name = "Electricity price"

    @property
    def device_info(self) -> DeviceInfo:
        address = self._get_address()
        place_id = self._get_site_id()
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}_{place_id}")},
            name=f"Karlstadsenergi ({address})",
            manufacturer="Karlstads Energi",
        )

    def _get_model(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        consumption = self.coordinator.data.get("consumption", {})
        return consumption.get("ConsumptionModel", {})

    def _get_address(self) -> str:
        return self._get_model().get("SiteName", "")

    def _get_site_id(self) -> str:
        return self._get_model().get("SiteId", "")

    def _get_total_kwh(self) -> float:
        """Get total kWh consumption for the fee period."""
        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if not series_list:
            return 0.0
        data_points = series_list[0].get("data", [])
        return sum(p.get("y", 0) for p in data_points)

    @property
    def native_value(self) -> float | None:
        """Return effective energy price in SEK/kWh.

        Calculated as ConsumptionFee (SEK) / total consumption (kWh).
        """
        if not self.coordinator.data:
            return None
        fee_data = self.coordinator.data.get("fee_data", {})
        fees = _extract_fee_series(fee_data)
        consumption_fee = fees.get(FEE_CONSUMPTION)
        if consumption_fee is None or consumption_fee <= 0:
            return None
        total_kwh = self._get_total_kwh()
        if total_kwh <= 0:
            return None
        return round(consumption_fee / total_kwh, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        fee_data = self.coordinator.data.get("fee_data", {})
        fees = _extract_fee_series(fee_data)
        total_kwh = self._get_total_kwh()
        attrs: dict[str, Any] = {
            "consumption_fee_sek": fees.get(FEE_CONSUMPTION),
            "power_fee_sek": fees.get(FEE_POWER),
            "fixed_fee_sek": fees.get(FEE_FIXED),
            "energy_tax_sek": fees.get(FEE_ENERGY_TAX),
            "vat_sek": fees.get(FEE_VAT),
            "total_invoice_sek": fees.get(FEE_SUM),
            "total_consumption_kwh": round(total_kwh, 1) if total_kwh else None,
        }
        # Calculate total variable cost per kWh (energy + grid + tax, ex VAT)
        variable_fees = sum(
            fees.get(k, 0) for k in (FEE_CONSUMPTION, FEE_POWER, FEE_ENERGY_TAX)
        )
        if total_kwh and variable_fees:
            attrs["total_variable_price_sek_kwh"] = round(variable_fees / total_kwh, 4)
        return attrs


class SpotPriceSensor(
    CoordinatorEntity[KarlstadsenergiSpotPriceCoordinator],
    SensorEntity,
):
    """Current Nord Pool spot price from Evado public API.

    Compatible with HA Energy Dashboard.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "SEK/kWh"
    _attr_icon = "mdi:flash"
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        coordinator: KarlstadsenergiSpotPriceCoordinator,
        customer_number: str,
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._attr_unique_id = f"{DOMAIN}_{customer_number}_spot_price"
        self._attr_name = "Spot price"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}")},
            name="Karlstadsenergi",
            manufacturer="Karlstads Energi",
        )

    @property
    def native_value(self) -> float | None:
        """Return current spot price in SEK/kWh."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("current_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        attrs: dict[str, Any] = {"region": data.get("region", "SE3")}

        # Current price in öre for reference
        current_sek = data.get("current_price")
        if current_sek is not None:
            attrs["price_ore_kwh"] = round(current_sek * 100, 2)

        # Today's prices summary
        prices = data.get("prices", [])
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        today = now.date()
        tomorrow = today + datetime.timedelta(days=1)

        today_prices = [p["price_sek"] for p in prices if p["start"].date() == today]
        if today_prices:
            attrs["today_min"] = min(today_prices)
            attrs["today_max"] = max(today_prices)
            attrs["today_average"] = round(sum(today_prices) / len(today_prices), 4)

        tomorrow_prices = [
            p["price_sek"] for p in prices if p["start"].date() == tomorrow
        ]
        if tomorrow_prices:
            attrs["tomorrow_min"] = min(tomorrow_prices)
            attrs["tomorrow_max"] = max(tomorrow_prices)
            attrs["tomorrow_average"] = round(
                sum(tomorrow_prices) / len(tomorrow_prices), 4
            )

        return attrs


class ContractSensor(
    CoordinatorEntity[KarlstadsenergiContractCoordinator],
    SensorEntity,
):
    """Sensor showing contract details."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:file-document-outline"

    def __init__(
        self,
        coordinator: KarlstadsenergiContractCoordinator,
        customer_number: str,
        contract: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._utility_name = contract.get("UtilityName", "")
        self._slug = _slug_for_contract(self._utility_name)
        self._contract_id = contract.get("ContractId", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_number}_contract_{self._slug}"
        self._attr_name = f"Contract {self._utility_name}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}")},
            name="Karlstadsenergi",
            manufacturer="Karlstads Energi",
        )

    def _get_contract(self) -> dict[str, Any]:
        """Find this contract in coordinator data."""
        if not self.coordinator.data:
            return {}
        for c in self.coordinator.data.get("contracts", []):
            if c.get("ContractId") == self._contract_id:
                return c
        return {}

    @property
    def native_value(self) -> str | None:
        """Return contract alternative (e.g. 'Fast månadspris')."""
        contract = self._get_contract()
        return contract.get("ContractAlternative") or contract.get("UtilityName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self._get_contract()
        if not contract:
            return {}
        return {
            "contract_id": contract.get("ContractId"),
            "contract_code": contract.get("ContractCode"),
            "contract_start_date": contract.get("ContractStartDate"),
            "contract_end_date": contract.get("ContractEndDate"),
            "utility_name": contract.get("UtilityName"),
            "gsrn_number": contract.get("GsrnNumber"),
            "net_area_code": contract.get("NetAreaCode"),
            "electricity_region": contract.get("ElecticityRegion"),
        }
