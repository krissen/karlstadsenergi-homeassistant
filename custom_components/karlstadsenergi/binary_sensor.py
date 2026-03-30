"""Binary sensor platform for Karlstadsenergi waste collection."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import KarlstadsenergiConfigEntry, KarlstadsenergiWasteCoordinator
from .const import (
    CONF_PERSONNUMMER,
    DOMAIN,
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
    """Set up Karlstadsenergi binary sensors."""
    waste_coordinator = entry.runtime_data.waste_coordinator
    customer_id = entry.data.get("customer_code") or entry.data[CONF_PERSONNUMMER]

    # If waste data has both empty services and empty next_dates at startup
    # (first fetch failed), register a coordinator listener so entities are
    # created when data becomes available.
    waste_entities_added = False

    def _add_waste_entities() -> None:
        nonlocal waste_entities_added
        if waste_entities_added or not waste_coordinator.data:
            return
        data = waste_coordinator.data
        services = data.get("services", [])
        next_dates = data.get("next_dates", [])
        new_entities: list[BinarySensorEntity] = []
        if services:
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                new_entities.append(
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
                new_entities.append(
                    WastePickupTomorrowSummarySensor(
                        coordinator=waste_coordinator,
                        customer_id=customer_id,
                        item=item,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)
            waste_entities_added = True

    waste_data = waste_coordinator.data
    if waste_data and (waste_data.get("services") or waste_data.get("next_dates")):
        _add_waste_entities()
    else:
        unsub = waste_coordinator.async_add_listener(_add_waste_entities)
        entry.async_on_unload(unsub)


class WastePickupTomorrowSensor(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    BinarySensorEntity,
):
    """Binary sensor: on when waste pickup is tomorrow (detailed mode)."""

    _attr_has_entity_name = True
    # device_class intentionally omitted: no BinarySensorDeviceClass
    # matches "upcoming scheduled event" semantics

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
        self._attr_translation_key = "pickup_tomorrow"
        self._attr_translation_placeholders = {"waste_type": self._waste_type}

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
    def is_on(self) -> bool | None:
        """Return True if pickup is tomorrow."""
        pickup_date = pickup_date_for_service(self.coordinator.data, self._service_id)
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
    # device_class intentionally omitted: no BinarySensorDeviceClass
    # matches "upcoming scheduled event" semantics

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

        self._attr_unique_id = f"{DOMAIN}_{customer_id}_{self._slug}_pickup_tomorrow"
        self._attr_translation_key = "pickup_tomorrow"
        self._attr_translation_placeholders = {"waste_type": self._waste_type}

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
    def is_on(self) -> bool | None:
        """Return True if pickup is tomorrow."""
        pickup_date = pickup_date_for_type(self.coordinator.data, self._waste_type)
        if pickup_date is None:
            return None
        return pickup_date == dt_util.now().date() + datetime.timedelta(days=1)

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:trash-can"
        return "mdi:trash-can-outline"
