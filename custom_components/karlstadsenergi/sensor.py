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
    KarlstadsenergiDistrictHeatingCoordinator,
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
    FEE_SENSORS,
    FEE_SUM,
    FEE_VAT,
    VERSION,
    FeeSensorInfo,
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
        consumption = runtime.consumption_coordinator.data.get("consumption") or {}
        model = consumption.get("ConsumptionModel") or {}
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
        services = data.get("services") or []
        next_dates = data.get("next_dates") or []
        new_entities: list[SensorEntity] = []
        if services:
            for service in services:
                if "FlexServiceId" not in service:
                    continue
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

    # Cost sensors (one per fee type, always created)
    for fee_id, fee_info in FEE_SENSORS.items():
        entities.append(
            ElectricityCostSensor(
                coordinator=runtime.consumption_coordinator,
                customer_id=customer_id,
                fee_id=fee_id,
                fee_info=fee_info,
                address=site_address,
                place_id=site_place_id,
            )
        )

    # District heating consumption sensor (always created; shows
    # unavailable when coordinator has no DH data or account lacks DH)
    entities.append(
        DistrictHeatingConsumptionSensor(
            coordinator=runtime.district_heating_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )

    # District heating price sensor
    entities.append(
        DistrictHeatingPriceSensor(
            coordinator=runtime.district_heating_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )

    # District heating cost sensors (one per fee type)
    for fee_id, fee_info in FEE_SENSORS.items():
        entities.append(
            DistrictHeatingCostSensor(
                coordinator=runtime.district_heating_coordinator,
                customer_id=customer_id,
                fee_id=fee_id,
                fee_info=fee_info,
                address=site_address,
                place_id=site_place_id,
            )
        )

    # District heating flow sensor (m³)
    entities.append(
        DistrictHeatingFlowSensor(
            coordinator=runtime.district_heating_coordinator,
            customer_id=customer_id,
            address=site_address,
            place_id=site_place_id,
        )
    )

    # District heating temperature difference sensor (dT)
    entities.append(
        DistrictHeatingDtSensor(
            coordinator=runtime.district_heating_coordinator,
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
        for contract in runtime.contract_coordinator.data.get("contracts") or []:
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

    Shows the cumulative period total (CurrYearValue from CompareModel,
    or sum of all daily chart points as fallback) as an informational
    sensor. No state_class is set because the portal API provides
    delayed historical data (hours/days lag), not real-time metering.

    For Energy Dashboard integration, use the external statistic
    ``karlstadsenergi:electricity_consumption_{customer_id}`` which is
    imported with correct hourly timestamps by the coordinator.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
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
        if self.coordinator.data:
            consumption = self.coordinator.data.get("consumption") or {}
        else:
            consumption = {}
        # Primary: use official period total from CompareModel
        compare = consumption.get("CompareModel") or {}
        curr_year_value = compare.get("CurrYearValue")
        if curr_year_value is not None:
            return round(float(curr_year_value), 3)

        # Fallback: sum all daily chart points
        chart = consumption.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return None
        data_points = series_list[0].get("data") or []
        if not data_points:
            return None
        total = sum(p.get("y", 0) for p in data_points if p.get("y") is not None)
        return round(float(total), 3) if total else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}

        if self.coordinator.data:
            consumption = self.coordinator.data.get("consumption") or {}
        else:
            consumption = {}

        # Comparison data
        compare = consumption.get("CompareModel") or {}
        if compare:
            attrs["total_last_year_period"] = compare.get("LastYearValue")
            attrs["difference_percentage"] = compare.get(
                "DifferencePercentage",
            )
            attrs["average_daily"] = compare.get("CurrYearAvg")
            attrs["average_daily_last_year"] = compare.get("LastYearAvg")

        # Monthly breakdown from chart data
        chart = consumption.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if series_list:
            data_points = series_list[0].get("data") or []
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
            self.coordinator.data.get("hourly") or {} if self.coordinator.data else {}
        )
        hourly_chart = hourly.get("DetailedConsumptionChart") or {}
        hourly_series = hourly_chart.get("SeriesList") or []
        if hourly_series:
            hourly_points = hourly_series[0].get("data") or []
            # Last 24 points
            recent = hourly_points[-24:] if len(hourly_points) >= 24 else hourly_points
            attrs["hourly_consumption"] = [
                {"time": p.get("dateInterval", ""), "kWh": p.get("y", 0)}
                for p in recent
            ]
            attrs["hourly_data_points"] = len(hourly_points)

        # Monthly kWh from wide-range data: latest complete month + YoY
        if self.coordinator.data:
            monthly_kwh = self.coordinator.data.get("monthly_kwh") or {}
        else:
            monthly_kwh = {}
        mkwh_chart = monthly_kwh.get("DetailedConsumptionChart") or {}
        mkwh_series = mkwh_chart.get("SeriesList") or []
        if mkwh_series:
            kwh_by_month: dict[str, float] = {}
            for p in mkwh_series[0].get("data") or []:
                di = p.get("dateInterval", "")
                val = p.get("y")
                if len(di) >= 7 and val is not None:
                    kwh_by_month[di[:7]] = round(float(val), 1)
            today = dt_util.now().date()
            current_month = today.strftime("%Y-%m")
            complete = sorted(m for m in kwh_by_month if m < current_month)
            if complete:
                latest = complete[-1]
                attrs["latest_month"] = latest
                attrs["latest_month_kwh"] = kwh_by_month[latest]
                # Previous month
                if len(complete) >= 2:
                    prev = complete[-2]
                    attrs["previous_month"] = prev
                    attrs["previous_month_kwh"] = kwh_by_month[prev]
                # Same month last year (fall back to previous month)
                try:
                    year, mon = latest.split("-")
                    yoy_key = f"{int(year) - 1}-{mon}"
                except (ValueError, IndexError):
                    yoy_key = None
                if yoy_key and yoy_key in kwh_by_month:
                    attrs["same_month_last_year"] = yoy_key
                    attrs["same_month_last_year_kwh"] = kwh_by_month[yoy_key]
                elif "previous_month_kwh" in attrs:
                    attrs["same_month_last_year"] = attrs["previous_month"]
                    attrs["same_month_last_year_kwh"] = attrs["previous_month_kwh"]

        return attrs


def _extract_fee_series(
    fee_data: dict, months: set[str] | None = None
) -> dict[str, float]:
    """Extract fee amounts from fee-type consumption response.

    Returns dict of series_id -> total SEK for the period.
    When months is provided, only data points within those months are summed.
    """
    chart = fee_data.get("DetailedConsumptionChart") or {}
    series_list = chart.get("SeriesList") or []
    fees: dict[str, float] = {}
    for series in series_list:
        series_id = series.get("id", "")
        if not series_id:
            continue
        data_points = series.get("data") or []
        if months is not None:
            total = sum(
                p.get("y", 0)
                for p in data_points
                if p.get("dateInterval", "")[:7] in months
            )
        else:
            total = sum(p.get("y", 0) for p in data_points)
        fees[series_id] = round(total, 2)
    return fees


def _extract_fee_months(fee_data: dict) -> set[str]:
    """Extract which months the fee data covers.

    Returns set of month keys like {"2026-02"} from the fee SeriesList
    dateInterval fields (e.g. "2026-02-01" -> "2026-02").
    """
    chart = fee_data.get("DetailedConsumptionChart") or {}
    series_list = chart.get("SeriesList") or []
    months: set[str] = set()
    for series in series_list:
        for point in series.get("data") or []:
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

    Compatible with HA Energy Dashboard.
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

    def _get_fee_kwh_by_month(self) -> dict[str, float]:
        """Build month -> kWh map for months present in both fee and consumption."""
        if not self.coordinator.data:
            return {}
        fee_data = self.coordinator.data.get("fee_data") or {}
        fee_months = _extract_fee_months(fee_data)
        if not fee_months:
            return {}
        monthly = self.coordinator.data.get("monthly_kwh") or {}
        chart = monthly.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return {}
        result: dict[str, float] = {}
        for p in series_list[0].get("data") or []:
            date_str = p.get("dateInterval", "")
            value = p.get("y")
            if len(date_str) >= 7 and value is not None:
                month = date_str[:7]
                if month in fee_months:
                    result[month] = float(value)
        return result

    def _compute_price(self) -> tuple[float | None, dict[str, Any]]:
        """Compute electricity price with fallback.

        Returns (price, attrs_dict). Primary: latest month. Fallback:
        period average over all overlapping months.
        """
        if not self.coordinator.data:
            return None, {}
        fee_data = self.coordinator.data.get("fee_data") or {}
        kwh_by_month = self._get_fee_kwh_by_month()
        if not kwh_by_month:
            return None, {}

        # Primary: latest month
        latest = max(kwh_by_month)
        latest_kwh = kwh_by_month[latest]
        if latest_kwh > 0:
            fees = _extract_fee_series(fee_data, months={latest})
            consumption_fee = fees.get(FEE_CONSUMPTION)
            if consumption_fee is not None:
                price = round(consumption_fee / latest_kwh, 4)
                attrs: dict[str, Any] = {
                    "price_source": "latest_month",
                    "fee_month": latest,
                    "consumption_kwh": round(latest_kwh, 1),
                    "consumption_fee_sek": fees.get(FEE_CONSUMPTION),
                    "power_fee_sek": fees.get(FEE_POWER),
                    "fixed_fee_sek": fees.get(FEE_FIXED),
                    "energy_tax_sek": fees.get(FEE_ENERGY_TAX),
                    "vat_sek": fees.get(FEE_VAT),
                    "total_fee_sek": fees.get(FEE_SUM),
                }
                variable = sum(
                    fees.get(k, 0) for k in (FEE_CONSUMPTION, FEE_POWER, FEE_ENERGY_TAX)
                )
                if variable:
                    attrs["total_variable_price_sek_kwh"] = round(
                        variable / latest_kwh, 4
                    )
                return price, attrs

        # Fallback: period average
        total_kwh = sum(kwh_by_month.values())
        if total_kwh <= 0:
            return None, {}
        months_set = set(kwh_by_month)
        fees = _extract_fee_series(fee_data, months=months_set)
        consumption_fee = fees.get(FEE_CONSUMPTION)
        if consumption_fee is None:
            return None, {}
        price = round(consumption_fee / total_kwh, 4)
        sorted_months = sorted(months_set)
        attrs = {
            "price_source": "period_average",
            "fee_month": f"{sorted_months[0]} - {sorted_months[-1]}",
            "months_count": len(sorted_months),
            "consumption_kwh": round(total_kwh, 1),
            "consumption_fee_sek": fees.get(FEE_CONSUMPTION),
            "power_fee_sek": fees.get(FEE_POWER),
            "fixed_fee_sek": fees.get(FEE_FIXED),
            "energy_tax_sek": fees.get(FEE_ENERGY_TAX),
            "vat_sek": fees.get(FEE_VAT),
            "total_fee_sek": fees.get(FEE_SUM),
        }
        variable = sum(
            fees.get(k, 0) for k in (FEE_CONSUMPTION, FEE_POWER, FEE_ENERGY_TAX)
        )
        if variable:
            attrs["total_variable_price_sek_kwh"] = round(variable / total_kwh, 4)
        return price, attrs

    @property
    def native_value(self) -> float | None:
        """Return effective energy price in SEK/kWh.

        Primary: latest invoiced month's price. Fallback: period average
        over all months with both fee and consumption data.
        """
        price, _ = self._compute_price()
        return price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, attrs = self._compute_price()
        return attrs


class ElectricityCostSensor(
    CoordinatorEntity[KarlstadsenergiConsumptionCoordinator],
    SensorEntity,
):
    """Monthly cost sensor for a specific fee type.

    Shows the latest month's fee amount (non-cumulative). Historical
    depth is provided by async_add_external_statistics in the
    coordinator rather than via recorder-derived statistics.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "SEK"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: KarlstadsenergiConsumptionCoordinator,
        customer_id: str,
        fee_id: str,
        fee_info: FeeSensorInfo,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._fee_id = fee_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_cost_{fee_info.stat_suffix}"
        self._attr_icon = fee_info.icon
        self._attr_translation_key = fee_info.translation_key

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

    def _get_series_points(self) -> list[dict]:
        """Get data points for this fee type from coordinator data."""
        if not self.coordinator.data:
            return []
        fee_data = self.coordinator.data.get("fee_data") or {}
        chart = fee_data.get("DetailedConsumptionChart") or {}
        for series in chart.get("SeriesList") or []:
            if series.get("id") == self._fee_id:
                return series.get("data") or []
        return []

    @property
    def native_value(self) -> float | None:
        """Return the latest month's fee amount in SEK."""
        data_points = self._get_series_points()
        if not data_points:
            return None
        sorted_points = sorted(data_points, key=lambda p: p.get("dateInterval", ""))
        last_value = sorted_points[-1].get("y")
        return round(float(last_value), 2) if last_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data_points = self._get_series_points()
        if not data_points:
            return {}
        monthly: dict[str, float] = {}
        for point in data_points:
            date_str = point.get("dateInterval", "")
            value = point.get("y")
            if date_str and value is not None:
                month_key = date_str[:7]
                monthly[month_key] = round(float(value), 2)
        if monthly:
            return {
                "monthly_breakdown": dict(sorted(monthly.items())),
                "fee_period_months": sorted(monthly.keys()),
            }
        return {}


class DistrictHeatingConsumptionSensor(
    CoordinatorEntity[KarlstadsenergiDistrictHeatingCoordinator],
    SensorEntity,
):
    """Sensor for district heating (fjärrvärme) consumption.

    Shows the cumulative period total from the DH consumption data.
    For Energy Dashboard integration, use the external statistic
    ``karlstadsenergi:district_heating_consumption_{customer_id}``.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:radiator"
    _attr_suggested_display_precision = 1
    _attr_translation_key = "district_heating_consumption"

    def __init__(
        self,
        coordinator: KarlstadsenergiDistrictHeatingCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_district_heating"

    @property
    def device_info(self) -> DeviceInfo:
        return _dh_device_info(self._customer_id, self._address, self._place_id)

    @property
    def available(self) -> bool:
        """Return True only if DH data is actually available."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("available", False)

    @property
    def native_value(self) -> float | None:
        """Return cumulative total kWh for the current period.

        Uses CompareModel CurrYearValue when available, falls back to
        summing all daily chart data points.
        """
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None
        consumption = self.coordinator.data.get("consumption") or {}

        # Primary: use official period total from CompareModel
        compare = consumption.get("CompareModel") or {}
        curr_year_value = compare.get("CurrYearValue")
        if curr_year_value is not None:
            return round(float(curr_year_value), 3)

        # Fallback: sum all daily chart points
        chart = consumption.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return None
        data_points = series_list[0].get("data") or []
        if not data_points:
            return None
        total = sum(p.get("y", 0) for p in data_points if p.get("y") is not None)
        return round(float(total), 3) if total else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}

        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return attrs

        consumption = self.coordinator.data.get("consumption") or {}

        # Comparison data
        compare = consumption.get("CompareModel") or {}
        if compare:
            attrs["total_last_year_period"] = compare.get("LastYearValue")
            attrs["difference_percentage"] = compare.get("DifferencePercentage")
            attrs["average_daily"] = compare.get("CurrYearAvg")
            attrs["average_daily_last_year"] = compare.get("LastYearAvg")

        # Monthly breakdown from chart data
        chart = consumption.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if series_list:
            data_points = series_list[0].get("data") or []
            monthly: dict[str, float] = {}
            for point in data_points:
                date_str = point.get("dateInterval", "")
                value = point.get("y", 0)
                if date_str and value:
                    month_key = date_str[:7]
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

        # Hourly data (last 24h)
        hourly = self.coordinator.data.get("hourly") or {}
        hourly_chart = hourly.get("DetailedConsumptionChart") or {}
        hourly_series = hourly_chart.get("SeriesList") or []
        if hourly_series:
            hourly_points = hourly_series[0].get("data") or []
            recent = hourly_points[-24:] if len(hourly_points) >= 24 else hourly_points
            attrs["hourly_consumption"] = [
                {"time": p.get("dateInterval", ""), "kWh": p.get("y", 0)}
                for p in recent
            ]
            attrs["hourly_data_points"] = len(hourly_points)

        # Monthly kWh from wide-range data
        monthly_kwh = self.coordinator.data.get("monthly_kwh") or {}
        mkwh_chart = monthly_kwh.get("DetailedConsumptionChart") or {}
        mkwh_series = mkwh_chart.get("SeriesList") or []
        if mkwh_series:
            kwh_by_month: dict[str, float] = {}
            for p in mkwh_series[0].get("data") or []:
                di = p.get("dateInterval", "")
                val = p.get("y")
                if len(di) >= 7 and val is not None:
                    kwh_by_month[di[:7]] = round(float(val), 1)
            today = dt_util.now().date()
            current_month = today.strftime("%Y-%m")
            complete = sorted(m for m in kwh_by_month if m < current_month)
            if complete:
                latest = complete[-1]
                attrs["latest_month"] = latest
                attrs["latest_month_kwh"] = kwh_by_month[latest]
                if len(complete) >= 2:
                    prev = complete[-2]
                    attrs["previous_month"] = prev
                    attrs["previous_month_kwh"] = kwh_by_month[prev]
                try:
                    year, mon = latest.split("-")
                    yoy_key = f"{int(year) - 1}-{mon}"
                except (ValueError, IndexError):
                    yoy_key = None
                if yoy_key and yoy_key in kwh_by_month:
                    attrs["same_month_last_year"] = yoy_key
                    attrs["same_month_last_year_kwh"] = kwh_by_month[yoy_key]

        return attrs


def _dh_device_info(
    customer_id: str, address: str, place_id: str
) -> DeviceInfo:
    """Build DeviceInfo for district heating sensors."""
    identifier = (
        f"{customer_id}_{place_id}_dh" if place_id else f"{customer_id}_dh"
    )
    name = (
        f"Karlstadsenergi Fjärrvärme ({address})"
        if address
        else "Karlstadsenergi Fjärrvärme"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name=name,
        manufacturer="Karlstads Energi",
        model="District Heating",
        sw_version=VERSION,
    )


class DistrictHeatingPriceSensor(
    CoordinatorEntity[KarlstadsenergiDistrictHeatingCoordinator],
    SensorEntity,
):
    """Effective district heating price derived from fee breakdown.

    Computed as consumption fee / kWh for the latest invoiced month.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "SEK/kWh"
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 4
    _attr_translation_key = "district_heating_price"

    def __init__(
        self,
        coordinator: KarlstadsenergiDistrictHeatingCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_district_heating_price"

    @property
    def device_info(self) -> DeviceInfo:
        return _dh_device_info(self._customer_id, self._address, self._place_id)

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("available", False)

    def _get_fee_kwh_by_month(self) -> dict[str, float]:
        """Build month -> kWh map for months present in both fee and consumption."""
        if not self.coordinator.data:
            return {}
        fee_data = self.coordinator.data.get("fee_data") or {}
        fee_months = _extract_fee_months(fee_data)
        if not fee_months:
            return {}
        monthly = self.coordinator.data.get("monthly_kwh") or {}
        chart = monthly.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return {}
        result: dict[str, float] = {}
        for p in series_list[0].get("data") or []:
            date_str = p.get("dateInterval", "")
            value = p.get("y")
            if len(date_str) >= 7 and value is not None:
                month = date_str[:7]
                if month in fee_months:
                    result[month] = float(value)
        return result

    def _compute_price(self) -> tuple[float | None, dict[str, Any]]:
        """Compute DH price. Primary: latest month. Fallback: period average."""
        if not self.coordinator.data or not self.coordinator.data.get("available"):
            return None, {}
        fee_data = self.coordinator.data.get("fee_data") or {}
        kwh_by_month = self._get_fee_kwh_by_month()
        if not kwh_by_month:
            return None, {}

        # Primary: latest month
        latest = max(kwh_by_month)
        latest_kwh = kwh_by_month[latest]
        if latest_kwh > 0:
            fees = _extract_fee_series(fee_data, months={latest})
            consumption_fee = fees.get(FEE_CONSUMPTION)
            if consumption_fee is not None:
                price = round(consumption_fee / latest_kwh, 4)
                attrs: dict[str, Any] = {
                    "price_source": "latest_month",
                    "fee_month": latest,
                    "consumption_kwh": round(latest_kwh, 1),
                    "consumption_fee_sek": fees.get(FEE_CONSUMPTION),
                    "power_fee_sek": fees.get(FEE_POWER),
                    "fixed_fee_sek": fees.get(FEE_FIXED),
                    "energy_tax_sek": fees.get(FEE_ENERGY_TAX),
                    "vat_sek": fees.get(FEE_VAT),
                    "total_fee_sek": fees.get(FEE_SUM),
                }
                variable = sum(
                    fees.get(k, 0)
                    for k in (FEE_CONSUMPTION, FEE_POWER, FEE_ENERGY_TAX)
                )
                if variable:
                    attrs["total_variable_price_sek_kwh"] = round(
                        variable / latest_kwh, 4
                    )
                return price, attrs

        # Fallback: period average
        total_kwh = sum(kwh_by_month.values())
        if total_kwh <= 0:
            return None, {}
        months_set = set(kwh_by_month)
        fees = _extract_fee_series(fee_data, months=months_set)
        consumption_fee = fees.get(FEE_CONSUMPTION)
        if consumption_fee is None:
            return None, {}
        price = round(consumption_fee / total_kwh, 4)
        sorted_months = sorted(months_set)
        attrs = {
            "price_source": "period_average",
            "fee_month": f"{sorted_months[0]} - {sorted_months[-1]}",
            "months_count": len(sorted_months),
            "consumption_kwh": round(total_kwh, 1),
            "consumption_fee_sek": fees.get(FEE_CONSUMPTION),
            "power_fee_sek": fees.get(FEE_POWER),
            "fixed_fee_sek": fees.get(FEE_FIXED),
            "energy_tax_sek": fees.get(FEE_ENERGY_TAX),
            "vat_sek": fees.get(FEE_VAT),
            "total_fee_sek": fees.get(FEE_SUM),
        }
        variable = sum(
            fees.get(k, 0) for k in (FEE_CONSUMPTION, FEE_POWER, FEE_ENERGY_TAX)
        )
        if variable:
            attrs["total_variable_price_sek_kwh"] = round(variable / total_kwh, 4)
        return price, attrs

    @property
    def native_value(self) -> float | None:
        price, _ = self._compute_price()
        return price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, attrs = self._compute_price()
        return attrs


class DistrictHeatingCostSensor(
    CoordinatorEntity[KarlstadsenergiDistrictHeatingCoordinator],
    SensorEntity,
):
    """Monthly cost sensor for a specific DH fee type.

    Shows the latest month's fee amount. Mirrors ElectricityCostSensor
    but for district heating.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "SEK"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: KarlstadsenergiDistrictHeatingCoordinator,
        customer_id: str,
        fee_id: str,
        fee_info: FeeSensorInfo,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._fee_id = fee_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = (
            f"{DOMAIN}_{customer_id}_dh_cost_{fee_info.stat_suffix}"
        )
        self._attr_icon = fee_info.icon
        self._attr_translation_key = f"dh_{fee_info.translation_key}"

    @property
    def device_info(self) -> DeviceInfo:
        return _dh_device_info(self._customer_id, self._address, self._place_id)

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("available", False)

    def _get_series_points(self) -> list[dict]:
        """Get data points for this fee type from coordinator data."""
        if not self.coordinator.data:
            return []
        fee_data = self.coordinator.data.get("fee_data") or {}
        chart = fee_data.get("DetailedConsumptionChart") or {}
        for series in chart.get("SeriesList") or []:
            if series.get("id") == self._fee_id:
                return series.get("data") or []
        return []

    @property
    def native_value(self) -> float | None:
        """Return the latest month's fee amount in SEK."""
        data_points = self._get_series_points()
        if not data_points:
            return None
        sorted_points = sorted(data_points, key=lambda p: p.get("dateInterval", ""))
        last_value = sorted_points[-1].get("y")
        return round(float(last_value), 2) if last_value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data_points = self._get_series_points()
        if not data_points:
            return {}
        monthly: dict[str, float] = {}
        for point in data_points:
            date_str = point.get("dateInterval", "")
            value = point.get("y")
            if date_str and value is not None:
                month_key = date_str[:7]
                monthly[month_key] = round(float(value), 2)
        if monthly:
            return {
                "monthly_breakdown": dict(sorted(monthly.items())),
                "fee_period_months": sorted(monthly.keys()),
            }
        return {}


class DistrictHeatingFlowSensor(
    CoordinatorEntity[KarlstadsenergiDistrictHeatingCoordinator],
    SensorEntity,
):
    """Sensor for district heating water flow (m³).

    Shows the cumulative flow volume for the current period.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-pump"
    _attr_suggested_display_precision = 1
    _attr_translation_key = "district_heating_flow"

    def __init__(
        self,
        coordinator: KarlstadsenergiDistrictHeatingCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_district_heating_flow"

    @property
    def device_info(self) -> DeviceInfo:
        return _dh_device_info(self._customer_id, self._address, self._place_id)

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        if not self.coordinator.data.get("available"):
            return False
        flow = self.coordinator.data.get("flow") or {}
        chart = flow.get("DetailedConsumptionChart") or {}
        return bool(chart.get("SeriesList"))

    @property
    def native_value(self) -> float | None:
        """Return cumulative flow total for the period."""
        if not self.coordinator.data:
            return None
        flow = self.coordinator.data.get("flow") or {}
        chart = flow.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return None
        data_points = series_list[0].get("data") or []
        if not data_points:
            return None
        total = sum(p.get("y", 0) for p in data_points if p.get("y") is not None)
        return round(float(total), 1) if total else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        flow = self.coordinator.data.get("flow") or {}
        chart = flow.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return attrs
        data_points = series_list[0].get("data") or []
        if data_points:
            # Monthly breakdown
            monthly: dict[str, float] = {}
            for point in data_points:
                date_str = point.get("dateInterval", "")
                value = point.get("y", 0)
                if date_str and value:
                    month_key = date_str[:7]
                    monthly[month_key] = monthly.get(month_key, 0) + value
            if monthly:
                attrs["monthly_flow_m3"] = {
                    k: round(v, 1) for k, v in monthly.items()
                }
            # Latest data point
            last = data_points[-1]
            attrs["latest_date"] = last.get("dateInterval", "")
            last_value = last.get("y")
            if last_value is not None:
                attrs["latest_daily_m3"] = round(float(last_value), 2)
        return attrs


class DistrictHeatingDtSensor(
    CoordinatorEntity[KarlstadsenergiDistrictHeatingCoordinator],
    SensorEntity,
):
    """Sensor for district heating temperature difference (dT).

    Shows the average temperature difference (supply - return) in °C.
    A higher dT means more efficient heat extraction from the water.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer-water"
    _attr_suggested_display_precision = 1
    _attr_translation_key = "district_heating_dt"

    def __init__(
        self,
        coordinator: KarlstadsenergiDistrictHeatingCoordinator,
        customer_id: str,
        address: str = "",
        place_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        self._customer_id = customer_id
        self._address = address
        self._place_id = place_id
        self._attr_unique_id = f"{DOMAIN}_{customer_id}_district_heating_dt"

    @property
    def device_info(self) -> DeviceInfo:
        return _dh_device_info(self._customer_id, self._address, self._place_id)

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        if not self.coordinator.data.get("available"):
            return False
        dt_data = self.coordinator.data.get("dt") or {}
        chart = dt_data.get("DetailedConsumptionChart") or {}
        return bool(chart.get("SeriesList"))

    @property
    def native_value(self) -> float | None:
        """Return latest daily average dT in °C."""
        if not self.coordinator.data:
            return None
        dt_data = self.coordinator.data.get("dt") or {}
        chart = dt_data.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return None
        data_points = series_list[0].get("data") or []
        if not data_points:
            return None
        # Show the latest data point (daily average dT)
        last = data_points[-1]
        value = last.get("y")
        return round(float(value), 1) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        dt_data = self.coordinator.data.get("dt") or {}
        chart = dt_data.get("DetailedConsumptionChart") or {}
        series_list = chart.get("SeriesList") or []
        if not series_list:
            return attrs
        data_points = series_list[0].get("data") or []
        if data_points:
            # Period average dT
            values = [p.get("y") for p in data_points if p.get("y") is not None]
            if values:
                attrs["period_average_dt"] = round(sum(values) / len(values), 1)
                attrs["period_min_dt"] = round(min(values), 1)
                attrs["period_max_dt"] = round(max(values), 1)
            # Monthly averages
            monthly_sums: dict[str, float] = {}
            monthly_counts: dict[str, int] = {}
            for point in data_points:
                date_str = point.get("dateInterval", "")
                value = point.get("y")
                if date_str and value is not None:
                    month_key = date_str[:7]
                    monthly_sums[month_key] = monthly_sums.get(month_key, 0) + value
                    monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
            if monthly_sums:
                attrs["monthly_average_dt"] = {
                    k: round(monthly_sums[k] / monthly_counts[k], 1)
                    for k in sorted(monthly_sums)
                }
            # Latest data point
            last = data_points[-1]
            attrs["latest_date"] = last.get("dateInterval", "")
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
        prices = data.get("prices") or []
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
        for c in self.coordinator.data.get("contracts") or []:
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
