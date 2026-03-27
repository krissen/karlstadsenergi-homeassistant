"""Sensor platform for Karlstadsenergi."""

from __future__ import annotations

import datetime
import logging
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

from . import (
    KarlstadsenergiConsumptionCoordinator,
    KarlstadsenergiWasteCoordinator,
)
from .const import CONF_CUSTOMER_NUMBER, DOMAIN, WASTE_TYPE_SLUG

_LOGGER = logging.getLogger(__name__)


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
    customer_number = entry.data[CONF_CUSTOMER_NUMBER]

    entities: list[SensorEntity] = []

    # Waste collection sensors
    if waste_coordinator.data:
        services = waste_coordinator.data.get("services", [])
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

    async_add_entities(entities, update_before_add=False)


class WasteCollectionSensor(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator], SensorEntity,
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


class ElectricityConsumptionSensor(
    CoordinatorEntity[KarlstadsenergiConsumptionCoordinator], SensorEntity,
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
        consumption = self.coordinator.data.get("consumption", {}) if self.coordinator.data else {}
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
                "ServiceIdentifier", "",
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
                    "dateInterval", "",
                )

        return attrs
