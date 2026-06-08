"""Shared base entity for the Karlstadsenergi integration."""

from __future__ import annotations

from typing import Any, TypeVar

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

_CoordinatorT = TypeVar("_CoordinatorT", bound=DataUpdateCoordinator)


class KarlstadsenergiEntity(CoordinatorEntity[_CoordinatorT]):
    """Base entity that retains its last value when an update fails.

    The portal can force re-authentication often -- a BankID session expires
    after ~15 minutes and cannot be kept alive. Rather than going unavailable
    (gray) on every failed update, entities keep showing their last successful
    value (the coordinator retains ``data``) and expose ``data_stale`` /
    ``last_updated`` so the staleness is visible. A re-authentication then just
    refreshes the values (and the energy/fee history backfills on the next
    successful fetch).
    """

    @property
    def available(self) -> bool:
        """Stay available as long as we have data, even after a failed update.

        Deliberately decoupled from ``coordinator.last_update_success`` so a
        transient outage or an expired session does not blank the entity.
        """
        return self.coordinator.data is not None

    @property
    def _staleness_attrs(self) -> dict[str, Any]:
        """Attributes describing data freshness, merged into every entity."""
        attrs: dict[str, Any] = {
            "data_stale": not self.coordinator.last_update_success,
        }
        last = getattr(self.coordinator, "last_success_time", None)
        if last is not None:
            attrs["last_updated"] = last.isoformat()
        return attrs

    @property
    def _entity_attrs(self) -> dict[str, Any]:
        """Entity-specific attributes. Subclasses override this instead of
        ``extra_state_attributes`` so freshness markers are always merged in."""
        return {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Entity attributes plus the shared freshness markers."""
        return {**self._entity_attrs, **self._staleness_attrs}
