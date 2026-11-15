"""Real HA entry shutdown/timers and registry, with portal/platform loading mocked."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.helpers.event import async_track_time_interval

from custom_components import karlstadsenergi as integration
from custom_components.karlstadsenergi import sensor
from custom_components.karlstadsenergi.const import (
    CONF_CONTRACTS,
    CONF_ELECTRICITY,
    CONF_SPOT,
    CONF_WASTE,
    DOMAIN,
)

from .test_features import selections
from .test_features import setup_environment as setup_environment
from .test_integration import _make_api, _make_hass


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_heartbeat", [False, True])
async def test_real_entry_unload_cancels_timers_and_preserves_registry(
    tmp_path, pending_heartbeat: bool
) -> None:
    hass = HomeAssistant(str(tmp_path))
    # Real HA owns timers/tasks/registry/unload callbacks; only platform forwarding
    # and config-entry persistence are replaced (no HA test-plugin dependency).
    hass.config_entries = _make_hass().config_entries
    api = _make_api()
    api.async_get_hourly_consumption.return_value = {}
    api.async_get_fee_consumption.return_value = {}
    api.async_get_monthly_consumption = AsyncMock(return_value={})
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={"personnummer": "123", "auth_method": "bankid"},
        options=selections(CONF_ELECTRICITY),
        source="user",
        version=1,
        minor_version=1,
        unique_id="123",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )
    loader = MagicMock(domain=DOMAIN)
    loader.async_get_component = AsyncMock(return_value=integration)
    hass.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(hass)
    await dr.async_get(hass).async_load()
    registry = er.async_get(hass)
    await registry.async_load()
    tracks = []

    def track(*args, **kwargs):
        cancel = async_track_time_interval(*args, **kwargs)
        tracks.append(cancel.__self__)
        return cancel

    started = asyncio.Event()

    async def heartbeat():
        started.set()
        await asyncio.Future()

    api.async_heartbeat.side_effect = heartbeat
    with (
        patch.object(integration, "KarlstadsenergiApi", return_value=api),
        patch.object(integration, "async_track_time_interval", side_effect=track),
        patch.object(integration, "_migrate_waste_unique_ids", new_callable=AsyncMock),
    ):
        try:
            ids = []
            for category in (CONF_ELECTRICITY, CONF_WASTE, CONF_ELECTRICITY):
                # Set up the replacement only after the previous real entry unload.
                object.__setattr__(entry, "options", MappingProxyType(selections(category)))
                entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
                assert await integration.async_setup_entry(hass, entry)
                entry._async_set_state(hass, ConfigEntryState.LOADED, None)
                runtime = entry.runtime_data
                coordinator = runtime.consumption_coordinator or runtime.waste_coordinator
                entry.async_on_unload(coordinator.async_add_listener(lambda: None))
                if category == CONF_ELECTRICITY:
                    entities = []
                    await sensor.async_setup_entry(
                        hass, entry, lambda new, entities=entities, **kwargs: entities.extend(new)
                    )
                    entity = registry.async_get_or_create(
                        "sensor", DOMAIN, entities[0].unique_id, config_entry=entry
                    )
                    ids.append(entity.entity_id)
                    if len(ids) == 1:
                        registry.async_update_entity(
                            entity.entity_id, name="My electricity", icon="mdi:flash"
                        )
                    else:
                        assert entity.name == "My electricity"
                        assert entity.icon == "mdi:flash"
                cache_timer = runtime.cache._store._delay_handle
                assert cache_timer is not None
                tracker = tracks[-1]
                timer = tracker._timer_handle
                assert not timer.cancelled()
                if pending_heartbeat:
                    tracker.action(None)
                    await started.wait()
                    tasks = set(entry._background_tasks)
                    assert tasks
                async with entry.setup_lock:
                    assert await entry.async_unload(hass, integration=loader)
                assert timer.cancelled()
                assert coordinator._shutdown_requested
                assert coordinator._unsub_refresh is None
                assert cache_timer.cancelled()
                assert runtime.cache._store._delay_handle is None
                if pending_heartbeat:
                    assert all(task.cancelled() for task in tasks)
                    started.clear()
                assert entry.state is ConfigEntryState.NOT_LOADED
                assert not hasattr(entry, "runtime_data")
            assert ids[0] == ids[1]
            assert hass.config_entries.async_unload_platforms.await_count == 3
            assert api.async_close.await_count == 3
        finally:
            await hass.async_stop(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [None, {"contracts": []}, {"contracts": [{}]}])
async def test_contract_registration_recovers_from_empty_startup(
    tmp_path, setup_environment, initial
) -> None:
    env = setup_environment
    hass, entry, platform = await _registration_platform(tmp_path)
    object.__setattr__(entry, "options", MappingProxyType(selections(CONF_CONTRACTS)))
    try:
        assert await integration.async_setup_entry(hass, entry)
        coordinator = entry.runtime_data.contract_coordinator
        coordinator.async_set_updated_data(initial)
        await sensor.async_setup_entry(hass, entry, platform._async_schedule_add_entities_for_entry)
        await hass.async_block_till_done()
        assert not platform.entities
        assert coordinator._listeners
        assert coordinator._unsub_refresh is not None

        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert len(platform.entities) == 1
        entity_id = next(iter(platform.entities))
        registered = er.async_get(hass).async_get(entity_id)
        assert registered.device_id is not None
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert list(platform.entities) == [entity_id]
        env.api.async_get_flex_services.assert_not_awaited()
    finally:
        await platform.async_reset()
        await entry.runtime_data.contract_coordinator.async_shutdown()
        await hass.async_stop(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("start_spot_only", [False, True])
async def test_spot_registration_preserves_device_on_feature_reload(
    tmp_path, setup_environment, start_spot_only
) -> None:
    env = setup_environment
    hass, entry, platform = await _registration_platform(tmp_path)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    spot_id = None
    device_id = None
    try:
        categories = [selections(CONF_ELECTRICITY, CONF_SPOT), selections(CONF_SPOT)]
        if start_spot_only:
            categories.insert(0, selections(CONF_SPOT))
        categories.append(selections(CONF_ELECTRICITY, CONF_SPOT))
        for options in categories:
            object.__setattr__(entry, "options", MappingProxyType(options))
            before = env.api.async_get_consumption.await_count
            assert await integration.async_setup_entry(hass, entry)
            await sensor.async_setup_entry(
                hass, entry, platform._async_schedule_add_entities_for_entry
            )
            await hass.async_block_till_done()
            current_id = registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_123_spot_price")
            registered = registry.async_get(current_id)
            assert current_id in platform.entities
            device = devices.async_get(registered.device_id)
            if not options[CONF_ELECTRICITY]:
                assert env.api.async_get_consumption.await_count == before
                assert entry.runtime_data.discovery is None
            if spot_id is None:
                spot_id = current_id
                if start_spot_only:
                    assert device.identifiers == {(DOMAIN, "123")}
                else:
                    assert device.identifiers == {(DOMAIN, "123_site-99")}
            assert current_id == spot_id
            if options[CONF_ELECTRICITY] and device_id is None:
                device_id = device.id
                devices.async_update_device(device_id, name_by_user="My electricity device")
            if device_id is not None:
                assert registered.device_id == device_id
                assert devices.async_get(device_id).name_by_user == "My electricity device"
            if options[CONF_ELECTRICITY]:
                electricity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{DOMAIN}_123_electricity"
                )
                assert registry.async_get(electricity_id).device_id == device_id
            await platform.async_reset()
            await integration.async_unload_entry(hass, entry)
            await entry.runtime_data.spot_price_coordinator.async_shutdown()
            if entry.runtime_data.consumption_coordinator is not None:
                await entry.runtime_data.consumption_coordinator.async_shutdown()
    finally:
        await platform.async_reset()
        await hass.async_stop(force=True)


async def _registration_platform(tmp_path):
    """Use real HA entity/device registration without loading unrelated integrations."""
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = _make_hass().config_entries
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={"personnummer": "123", "auth_method": "bankid"},
        options={},
        source="user",
        version=1,
        minor_version=1,
        unique_id="123",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )
    hass.config_entries.async_get_entry.return_value = entry
    hass.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(hass)
    await dr.async_get(hass).async_load()
    await er.async_get(hass).async_load()
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="sensor",
        platform_name=DOMAIN,
        platform=sensor,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    return hass, entry, platform
