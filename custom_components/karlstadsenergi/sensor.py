"""Sensor platform for Karlstadsenergi."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import (
    KarlstadsenergiConfigEntry,
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
    VERSION,
    pickup_date_for_service,
    pickup_date_for_type,
    slug_for_waste_type,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KarlstadsenergiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Karlstadsenergi sensors."""
    runtime = entry.runtime_data
    customer_id = entry.data.get("customer_code") or entry.data[CONF_PERSONNUMMER]

    entities: list[SensorEntity] = []

    # Extract address/place_id from consumption data for device grouping.
    # These are captured at setup time for stable device identifiers (Blocker B).
    site_address = ""
    site_place_id = ""
    if runtime.consumption_coordinator.data:
        consumption = runtime.consumption_coordinator.data.get("consumption", {})
        model = consumption.get("ConsumptionModel", {})
        site_address = model.get("SiteName", "")
        site_place_id = model.get("SiteId", "")

    # Waste collection sensors.
    # If data has both empty services and empty next_dates at startup (first
    # fetch failed), register a coordinator listener so entities are created
    # when data becomes available.
    waste_entities_added = False

    def _add_waste_entities() -> None:
        nonlocal waste_entities_added
        if waste_entities_added or not runtime.waste_coordinator.data:
            return
        data = runtime.waste_coordinator.data
        services = data.get("services", [])
        next_dates = data.get("next_dates", [])
        new_entities: list[SensorEntity] = []
        if services:
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                new_entities.append(
                    WasteCollectionSensor(
                        coordinator=runtime.waste_coordinator,
                        customer_id=customer_id,
                        service=service,
                    )
                )
        elif next_dates:
            for item in next_dates:
                waste_type = item.get("Type", "")
                if not waste_type:
                    continue
                new_entities.append(
                    WasteCollectionSummary(
                        coordinator=runtime.waste_coordinator,
                        customer_id=customer_id,
                        item=item,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)
            waste_entities_added = True

    waste_data = runtime.waste_coordinator.data
    if waste_data and (waste_data.get("services") or waste_data.get("next_dates")):
        _add_waste_entities()
    else:
        unsub_waste = runtime.waste_coordinator.async_add_listener(_add_waste_entities)
        entry.async_on_unload(unsub_waste)

    # Electricity consumption + price sensors: always created so entities
    # don't disappear permanently after a transient startup failure.
    # CoordinatorEntity handles unavailability when coordinator.data is None.
    entities.append(
        ElectricityConsumptionSensor(
            coordinator=runtime.consumption_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )
    entities.append(
        ElectricityPriceSensor(
            coordinator=runtime.consumption_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )

    # Spot price sensor (always created -- shows unavailable if API is down)
    entities.append(
        SpotPriceSensor(
            coordinator=runtime.spot_price_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )

    # Contract sensors (one per contract).
    # If contract_coordinator.data is None at setup (first fetch failed),
    # register a listener so contract sensors are created when data arrives.
    contract_entities_added = False

    def _add_contracts() -> None:
        nonlocal contract_entities_added
        if contract_entities_added or not runtime.contract_coordinator.data:
            return
        new_entities: list[SensorEntity] = []
        for contract in runtime.contract_coordinator.data.get("contracts", []):
            utility = contract.get("UtilityName", "")
            if utility:
                new_entities.append(
                    ContractSensor(
                        coordinator=runtime.contract_coordinator,
                        customer_id=customer_id,
                        contract=contract,
                        address=site_address,
                        place_id=site_place_id,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)
            contract_entities_added = True

    if runtime.contract_coordinator.data:
        _add_contracts()
    else:
        unsub_contracts = runtime.contract_coordinator.async_add_listener(
            _add_contracts
        )
        entry.async_on_unload(unsub_contracts)

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
        customer_id: str,
        service: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._service_id = service["FlexServiceId"]
        self._waste_type = service.get("FlexServiceContainTypeValue", "")
        self._slug = slug_for_waste_type(self._waste_type)
        self._address = service.get("FlexServicePlaceAddress", "")
        self._container_size = service.get("SizeOfFlexIndividual", "")
        self._frequency = service.get("FetchFrequency", "")
        self._place_id = service.get("FlexServicePlaceId", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_id}_{self._place_id}_{self._slug}"
        # Review note (V7): Entity names use the Swedish waste type string
        # from the API (e.g. "Mat- och restavfall") intentionally. Translating
        # them would break the match with the actual service names shown on
        # the Karlstadsenergi portal.
        self._attr_name = self._waste_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_id}_{self._place_id}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
            model="Waste Collection",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> datetime.date | None:
        """Return next pickup date."""
        return pickup_date_for_service(self.coordinator.data, self._service_id)

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
            today = dt_util.now().date()
            delta = (pickup_date - today).days
            attrs["days_until_pickup"] = max(delta, 0)
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
        customer_id: str,
        item: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._waste_type = item.get("Type", "")
        self._slug = slug_for_waste_type(self._waste_type)
        self._address = item.get("Address", "").strip()
        self._container_size = item.get("Size", "")

        # Review note (V6): Summary mode unique_id lacks place_id because the
        # start-page API response doesn't reliably include it. Acceptable since
        # summary mode is the fallback when detailed services are unavailable.
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_{self._slug}"
        self._attr_name = self._waste_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_id}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
            model="Waste Collection",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> datetime.date | None:
        return pickup_date_for_type(self.coordinator.data, self._waste_type)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "address": self._address,
            "container_size": self._container_size,
        }
        pickup_date = self.native_value
        if pickup_date:
            today = dt_util.now().date()
            delta = (pickup_date - today).days
            attrs["days_until_pickup"] = max(delta, 0)
            attrs["pickup_is_today"] = delta == 0
            attrs["pickup_is_tomorrow"] = delta == 1
        return attrs


class ElectricityConsumptionSensor(
    CoordinatorEntity[KarlstadsenergiConsumptionCoordinator],
    SensorEntity,
):
    """Sensor for electricity consumption.

    Uses TOTAL_INCREASING state_class for HA Energy Dashboard
    compatibility. The native_value is the cumulative period total
    (CurrYearValue from CompareModel, or sum of all daily chart points
    as fallback). The value increases monotonically within a year and
    resets in January; TOTAL_INCREASING handles this automatically
    without requiring a last_reset property.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:flash"
    _attr_suggested_display_precision = 1
    _attr_translation_key = "electricity_consumption"

    def __init__(
        self,
        coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_electricity"

    @property
    def device_info(self) -> DeviceInfo:
        identifier = (
            f"{self._customer_id}_{self._place_id}"
            if self._place_id
            else self._customer_id
        )
        name = (
            f"Karlstadsenergi ({self._address})" if self._address else "Karlstadsenergi"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=name,
            manufacturer="Karlstads Energi",
            model="Electricity",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> float | None:
        """Return cumulative total kWh for the current period.

        Uses CurrYearValue from CompareModel (the official period total from
        the API) when available. Falls back to summing all data[].y values
        from SeriesList[0].

        Note: This value may lag days/weeks behind real-time because the
        portal API only provides historical data. The ``latest_date``
        attribute exposes the actual data date so users can judge staleness.
        """
        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )
        # Primary: use official period total from CompareModel
        compare = consumption.get("CompareModel", {})
        curr_year_value = compare.get("CurrYearValue")
        if curr_year_value is not None:
            return round(float(curr_year_value), 3)

        # Fallback: sum all daily chart points
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if not series_list:
            return None
        data_points = series_list[0].get("data", [])
        if not data_points:
            return None
        total = sum(p.get("y", 0) for p in data_points if p.get("y") is not None)
        return round(float(total), 3) if total else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}

        consumption = (
            self.coordinator.data.get("consumption", {})
            if self.coordinator.data
            else {}
        )

        # Comparison data
        compare = consumption.get("CompareModel", {})
        if compare:
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

            # Latest date and latest daily value
            if data_points:
                last = data_points[-1]
                attrs["latest_date"] = last.get("dateInterval", "")
                last_value = last.get("y")
                if last_value is not None:
                    attrs["latest_daily_kwh"] = round(float(last_value), 3)

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


def _extract_fee_months(fee_data: dict) -> set[str]:
    """Extract which months the fee data covers.

    Returns set of month keys like {"2026-02"} from the fee SeriesList
    dateInterval fields (e.g. "2026-02-01" -> "2026-02").
    """
    chart = fee_data.get("DetailedConsumptionChart", {})
    series_list = chart.get("SeriesList", [])
    months: set[str] = set()
    for series in series_list:
        for point in series.get("data", []):
            date_str = point.get("dateInterval", "")
            if len(date_str) >= 7:
                months.add(date_str[:7])
    return months


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
    _attr_translation_key = "electricity_price"

    def __init__(
        self,
        coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_electricity_price"

    @property
    def device_info(self) -> DeviceInfo:
        identifier = (
            f"{self._customer_id}_{self._place_id}"
            if self._place_id
            else self._customer_id
        )
        name = (
            f"Karlstadsenergi ({self._address})" if self._address else "Karlstadsenergi"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=name,
            manufacturer="Karlstads Energi",
            model="Electricity",
            sw_version=VERSION,
        )

    def _get_total_kwh_for_fee_period(self) -> float:
        """Get total kWh consumption matching the fee data's months only."""
        if not self.coordinator.data:
            return 0.0
        fee_data = self.coordinator.data.get("fee_data", {})
        fee_months = _extract_fee_months(fee_data)
        if not fee_months:
            return 0.0

        consumption = self.coordinator.data.get("consumption", {})
        chart = consumption.get("DetailedConsumptionChart", {})
        series_list = chart.get("SeriesList", [])
        if not series_list:
            return 0.0
        data_points = series_list[0].get("data", [])
        return sum(
            p.get("y", 0)
            for p in data_points
            if p.get("dateInterval", "")[:7] in fee_months
        )

    @property
    def native_value(self) -> float | None:
        """Return effective energy price in SEK/kWh.

        Calculated as ConsumptionFee (SEK) / consumption (kWh) for the
        same month(s) that the fee data covers.
        """
        if not self.coordinator.data:
            return None
        fee_data = self.coordinator.data.get("fee_data", {})
        fees = _extract_fee_series(fee_data)
        consumption_fee = fees.get(FEE_CONSUMPTION)
        if consumption_fee is None:
            return None
        total_kwh = self._get_total_kwh_for_fee_period()
        if total_kwh <= 0:
            return None
        return round(consumption_fee / total_kwh, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        fee_data = self.coordinator.data.get("fee_data", {})
        fees = _extract_fee_series(fee_data)
        total_kwh = self._get_total_kwh_for_fee_period()
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
        # Expose the fee data's time period so users can see if the price
        # calculation might be inaccurate due to partial month coverage (M8).
        fee_months = _extract_fee_months(fee_data)
        if fee_months:
            attrs["fee_period_months"] = sorted(fee_months)
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
    _attr_translation_key = "spot_price"

    def __init__(
        self,
        coordinator: KarlstadsenergiSpotPriceCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_spot_price"

    @property
    def device_info(self) -> DeviceInfo:
        identifier = (
            f"{self._customer_id}_{self._place_id}"
            if self._place_id
            else self._customer_id
        )
        name = (
            f"Karlstadsenergi ({self._address})" if self._address else "Karlstadsenergi"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=name,
            manufacturer="Karlstads Energi",
            model="Electricity",
            sw_version=VERSION,
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
        attrs["stale"] = data.get("stale", False)

        # Current price in öre for reference
        current_sek = data.get("current_price")
        if current_sek is not None:
            attrs["price_ore_kwh"] = round(current_sek * 100, 2)

        # Today's prices summary (use local time for correct day boundaries)
        prices = data.get("prices", [])
        local_now = dt_util.now()
        today = local_now.date()
        tomorrow = today + datetime.timedelta(days=1)

        today_prices = [
            p["price_sek"]
            for p in prices
            if p["start"].astimezone(local_now.tzinfo).date() == today
        ]
        if today_prices:
            attrs["today_min"] = min(today_prices)
            attrs["today_max"] = max(today_prices)
            attrs["today_average"] = round(sum(today_prices) / len(today_prices), 4)

        tomorrow_prices = [
            p["price_sek"]
            for p in prices
            if p["start"].astimezone(local_now.tzinfo).date() == tomorrow
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:file-document-outline"

    def __init__(
        self,
        coordinator: KarlstadsenergiContractCoordinator,
        customer_id: str,
        contract: dict[str, Any],
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._utility_name = contract.get("UtilityName", "")
        self._slug = _slug_for_contract(self._utility_name)
        self._contract_id = contract.get("ContractId", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_id}_contract_{self._contract_id}"
        self._attr_translation_key = "contract"
        self._attr_translation_placeholders = {"utility_name": self._utility_name}

    @property
    def device_info(self) -> DeviceInfo:
        identifier = (
            f"{self._customer_id}_{self._place_id}"
            if self._place_id
            else self._customer_id
        )
        name = (
            f"Karlstadsenergi ({self._address})" if self._address else "Karlstadsenergi"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=name,
            manufacturer="Karlstads Energi",
            model="Contract",
            sw_version=VERSION,
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
        """Return contract alternative (e.g. 'Fast månadspris').

        Truncated to 255 characters (HA state max length).
        """
        contract = self._get_contract()
        value = contract.get("ContractAlternative") or contract.get("UtilityName")
        if value and len(value) > 255:
            return value[:255]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self._get_contract()
        if not contract:
            return {}
        return {
            "contract_id": contract.get("ContractId"),
            "contract_start_date": contract.get("ContractStartDate"),
            "contract_end_date": contract.get("ContractEndDate"),
            "utility_name": contract.get("UtilityName"),
            # GsrnNumber omitted: it is a personally identifiable infrastructure
            # identifier for Swedish electricity customers and must not be exposed
            # as a default entity attribute.
            "net_area_code": contract.get("NetAreaCode"),
            # API key is misspelled upstream ("ElecticityRegion" not "ElectricityRegion")
            "electricity_region": contract.get("ElecticityRegion"),
        }
