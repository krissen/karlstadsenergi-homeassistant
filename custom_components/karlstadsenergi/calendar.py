"""Calendar platform for Karlstadsenergi waste collection."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KarlstadsenergiWasteCoordinator
from .const import CONF_PERSONNUMMER, DOMAIN, WASTE_TYPE_SLUG


def _slug_for_waste_type(waste_type: str) -> str:
    """Get English slug for a Swedish waste type name."""
    slug = WASTE_TYPE_SLUG.get(waste_type)
    if slug:
        return slug
    return "".join(c if c.isalnum() else "_" for c in waste_type.lower()).strip("_")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Karlstadsenergi calendar entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    waste_coordinator: KarlstadsenergiWasteCoordinator = data["waste_coordinator"]
    customer_number = entry.data[CONF_PERSONNUMMER]

    entities: list[CalendarEntity] = []

    if waste_coordinator.data:
        services = waste_coordinator.data.get("services", [])
        next_dates = waste_coordinator.data.get("next_dates", [])

        if services:
            for service in services:
                waste_type = service.get("FlexServiceContainTypeValue", "")
                if not waste_type:
                    continue
                entities.append(
                    WasteCollectionCalendar(
                        coordinator=waste_coordinator,
                        customer_number=customer_number,
                        service=service,
                    )
                )
        elif next_dates:
            for item in next_dates:
                waste_type = item.get("Type", "")
                if not waste_type:
                    continue
                entities.append(
                    WasteCollectionSummaryCalendar(
                        coordinator=waste_coordinator,
                        customer_number=customer_number,
                        item=item,
                    )
                )

    async_add_entities(entities, update_before_add=False)


class WasteCollectionCalendar(
    CoordinatorEntity[KarlstadsenergiWasteCoordinator],
    CalendarEntity,
):
    """Calendar entity for waste collection (detailed mode)."""

    _attr_has_entity_name = True

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
        self._frequency = service.get("FetchFrequency", "")
        self._place_id = service.get("FlexServicePlaceId", "")

        self._attr_unique_id = f"{DOMAIN}_{customer_number}_{self._slug}_calendar"
        self._attr_name = self._waste_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}_{self._place_id}")},
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
        pickup_date = self._next_pickup_date()
        if pickup_date is None:
            return None
        return self._make_event(pickup_date)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return events in the given date range."""
        pickup_date = self._next_pickup_date()
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
        customer_number: str,
        item: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._customer_number = customer_number
        self._waste_type = item.get("Type", "")
        self._slug = _slug_for_waste_type(self._waste_type)
        self._address = item.get("Address", "").strip()

        self._attr_unique_id = f"{DOMAIN}_{customer_number}_{self._slug}_calendar"
        self._attr_name = self._waste_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._customer_number}")},
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
        pickup_date = self._next_pickup_date()
        if pickup_date is None:
            return None
        return self._make_event(pickup_date)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return events in the given date range."""
        pickup_date = self._next_pickup_date()
        if pickup_date is None:
            return []
        start_d = start_date.date()
        end_d = end_date.date()
        if start_d <= pickup_date < end_d:
            return [self._make_event(pickup_date)]
        return []
