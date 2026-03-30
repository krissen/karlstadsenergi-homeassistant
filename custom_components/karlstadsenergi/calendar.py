"""Calendar platform for Karlstadsenergi waste collection."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    """Set up Karlstadsenergi calendar entities."""
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
        new_entities: list[CalendarEntity] = []
        if services:
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                new_entities.append(
                    WasteCollectionCalendar(
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
                    WasteCollectionSummaryCalendar(
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


class WasteCollectionCalendar(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    CalendarEntity,
):
    """Calendar entity for waste collection (detailed mode)."""

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
        self._frequency = service.get("FetchFrequency", "")
        self._place_id = service.get("FlexServicePlaceId", "")

        self._attr_unique_id = (
            f"{DOMAIN}_{customer_id}_{self._place_id}_{self._slug}_calendar"
        )
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

    def _make_event(self, pickup_date: datetime.date) -> CalendarEvent:
        """Create a CalendarEvent for a pickup date."""
        summary = self._waste_type
        if self._frequency:
            summary = f"{self._waste_type} ({self._frequency})"
        return CalendarEvent(
            summary=summary,
            start=pickup_date,
            end=pickup_date + datetime.timedelta(days=1),
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming pickup as a calendar event."""
        pickup_date = pickup_date_for_service(self.coordinator.data, self._service_id)
        if pickup_date is None:
            return None
        return self._make_event(pickup_date)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return events in the given date range.

        Note: Returns at most one event per waste type because the
        Karlstadsenergi API only exposes the *next* scheduled pickup
        date, not a full recurring schedule.
        """
        pickup_date = pickup_date_for_service(self.coordinator.data, self._service_id)
        if pickup_date is None:
            return []
        start_d = start_date.date()
        end_d = end_date.date()
        if start_d <= pickup_date < end_d:
            return [self._make_event(pickup_date)]
        return []


class WasteCollectionSummaryCalendar(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    CalendarEntity,
):
    """Calendar entity for waste collection (summary/fallback mode)."""

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

        self._attr_unique_id = f"{DOMAIN}_{customer_id}_{self._slug}_calendar"
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

    def _make_event(self, pickup_date: datetime.date) -> CalendarEvent:
        """Create a CalendarEvent for a pickup date."""
        return CalendarEvent(
            summary=self._waste_type,
            start=pickup_date,
            end=pickup_date + datetime.timedelta(days=1),
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming pickup as a calendar event."""
        pickup_date = pickup_date_for_type(self.coordinator.data, self._waste_type)
        if pickup_date is None:
            return None
        return self._make_event(pickup_date)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return events in the given date range.

        Note: same single-event limitation as WasteCollectionCalendar
        (API only provides the next pickup date).
        """
        pickup_date = pickup_date_for_type(self.coordinator.data, self._waste_type)
        if pickup_date is None:
            return []
        start_d = start_date.date()
        end_d = end_date.date()
        if start_d <= pickup_date < end_d:
            return [self._make_event(pickup_date)]
        return []
