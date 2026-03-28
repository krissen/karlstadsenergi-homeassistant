"""Binary sensor platform for Karlstadsenergi waste collection."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import KarlstadsenergiConfigEntry, KarlstadsenergiWasteCoordinator
from .const import CONF_PERSONNUMMER, DOMAIN, slug_for_waste_type


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KarlstadsenergiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Karlstadsenergi binary sensors."""
    waste_coordinator = entry.runtime_data.waste_coordinator
    customer_id = entry.data.get("customer_code") or entry.data[CONF_PERSONNUMMER]

    entities: list[BinarySensorEntity] = []

    if waste_coordinator.data:
        services = waste_coordinator.data.get("services", [])
        next_dates = waste_coordinator.data.get("next_dates", [])

        if services:
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                entities.append(
                    WastePickupTomorrowSensor(
                        coordinator=waste_coordinator,
                        customer_id=customer_id,
                        service=service,
                    )
                )
        elif next_dates:
            for item in next_dates:
                waste_type = item.get("Type", "")
                if not waste_type:
                    continue
                entities.append(
                    WastePickupTomorrowSummarySensor(
                        coordinator=waste_coordinator,
                        customer_id=customer_id,
                        item=item,
                    )
                )

    async_add_entities(entities, update_before_add=False)


class WastePickupTomorrowSensor(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    BinarySensorEntity,
):
    """Binary sensor: on when waste pickup is tomorrow (detailed mode)."""

    _attr_has_entity_name = True

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
        self._place_id = service.get("FlexServicePlaceId", "")

        self._attr_unique_id = (
            f"{DOMAIN}_{customer_id}_{self._place_id}_{self._slug}_pickup_tomorrow"
        )
        self._attr_name = f"{self._waste_type} pickup tomorrow"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_id}_{self._place_id}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
        )

    def _next_pickup_date(self) -> datetime.date | None:
        """Return the next pickup date from coordinator data."""
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
    def is_on(self) -> bool | None:
        """Return True if pickup is tomorrow."""
        pickup_date = self._next_pickup_date()
        if pickup_date is None:
            return None
        return pickup_date == dt_util.now().date() + datetime.timedelta(days=1)

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:trash-can"
        return "mdi:trash-can-outline"


class WastePickupTomorrowSummarySensor(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    BinarySensorEntity,
):
    """Binary sensor: on when waste pickup is tomorrow (summary mode)."""

    _attr_has_entity_name = True

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

        self._attr_unique_id = (
            f"{DOMAIN}_{customer_id}_{self._slug}_pickup_tomorrow"
        )
        self._attr_name = f"{self._waste_type} pickup tomorrow"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_id}")},
            name=f"Karlstadsenergi ({self._address})",
            manufacturer="Karlstads Energi",
        )

    def _next_pickup_date(self) -> datetime.date | None:
        """Return the next pickup date from coordinator data."""
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
    def is_on(self) -> bool | None:
        """Return True if pickup is tomorrow."""
        pickup_date = self._next_pickup_date()
        if pickup_date is None:
            return None
        return pickup_date == dt_util.now().date() + datetime.timedelta(days=1)

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:trash-can"
        return "mdi:trash-can-outline"
