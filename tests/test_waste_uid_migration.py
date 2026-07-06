"""Tests for the waste unique_id migration map.

When Karlstadsenergi renames a waste service (e.g. "Glas/Metall" ->
"Glas- och metallförpackningar") the old name-slug unique_id changes, which
orphans the entity. _waste_uid_migration_map re-keys current services from the
legacy slug-based unique_id to the stable FlexServiceId-based one.
"""

from __future__ import annotations

from custom_components.karlstadsenergi import _waste_uid_migration_map
from custom_components.karlstadsenergi.const import DOMAIN, slug_for_waste_type


def _service(
    service_id: int = 23544343926,
    place_id: str = "P1",
    name: str = "Glas- och metallförpackningar",
) -> dict:
    return {
        "FlexServiceId": service_id,
        "FlexServicePlaceId": place_id,
        "FlexServiceContainTypeValue": name,
    }


def test_map_rekeys_all_three_platforms_to_service_id() -> None:
    mapping = _waste_uid_migration_map("CUST", [_service()])

    slug = slug_for_waste_type("Glas- och metallförpackningar")
    old = f"{DOMAIN}_CUST_P1_{slug}"
    new = f"{DOMAIN}_CUST_P1_23544343926"

    assert mapping[("sensor", old)] == new
    assert mapping[("binary_sensor", f"{old}_pickup_tomorrow")] == (
        f"{new}_pickup_tomorrow"
    )
    assert mapping[("calendar", f"{old}_calendar")] == f"{new}_calendar"
    # Exactly one entry per platform for the single service.
    assert len(mapping) == 3


def test_map_uses_stable_service_id_not_name() -> None:
    """The target unique_id must not contain the (renamable) name slug."""
    mapping = _waste_uid_migration_map("CUST", [_service()])
    for new_uid in mapping.values():
        assert new_uid.endswith("23544343926") or "_23544343926_" in new_uid
        assert "glas" not in new_uid


def test_service_without_flex_service_id_is_skipped() -> None:
    services = [{"FlexServicePlaceId": "P1", "FlexServiceContainTypeValue": "X"}]
    assert _waste_uid_migration_map("CUST", services) == {}


def test_empty_services_yields_empty_map() -> None:
    assert _waste_uid_migration_map("CUST", []) == {}
