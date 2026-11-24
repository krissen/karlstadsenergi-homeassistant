"""Category isolation, persistence and lifecycle without live portal credentials."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.karlstadsenergi import (
    SITE_CACHE_KEY,
    KarlstadsenergiSpotPriceCoordinator,
    _async_reload_entry,
    async_setup_entry,
    async_unload_entry,
    binary_sensor,
    calendar,
    sensor,
)
from custom_components.karlstadsenergi.api import (
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from custom_components.karlstadsenergi.config_flow import KarlstadsenergiOptionsFlow
from custom_components.karlstadsenergi.const import (
    CONF_CONTRACTS,
    CONF_DISTRICT_HEATING,
    CONF_ELECTRICITY,
    CONF_HISTORY_YEARS,
    CONF_SPOT,
    CONF_UPDATE_INTERVAL,
    CONF_WASTE,
    DOMAIN,
    FEATURE_KEYS,
    NEW_FEATURE_DEFAULTS,
    resolve_features,
)
from custom_components.karlstadsenergi.diagnostics import async_get_config_entry_diagnostics

from .conftest import load_fixture
from .test_config_flow import _make_flow, _mock_password_api
from .test_integration import _FakeCache, _make_api, _make_entry, _make_hass, _persistent_cache

COORDINATORS = (
    "waste_coordinator",
    "consumption_coordinator",
    "district_heating_coordinator",
    "contract_coordinator",
    "spot_price_coordinator",
)


def selections(*enabled: str) -> dict[str, bool]:
    return {key: key in enabled for key in FEATURE_KEYS}


@pytest.fixture
def setup_environment() -> Iterator[SimpleNamespace]:
    hass = _make_hass()
    hass.async_run_hass_job.side_effect = lambda job, **kwargs: asyncio.create_task(job.target())
    api = _make_api()
    response = json.loads(load_fixture("consumption_onload")["d"])
    response["ConsumptionModel"]["SelectedSiteGroupNode"] = {"Utilities": [{"UtilityId": "F"}]}
    api.async_get_consumption.return_value = response
    api.async_get_monthly_consumption = AsyncMock(return_value={})
    api.async_get_consumption_with_model = AsyncMock(return_value={})
    api.async_get_flex_services.return_value = [
        {
            "FlexServiceId": 42,
            "FlexServicePlaceId": "place",
            "FSStatusName": "Aktiv",
            "FlexServiceContainTypeValue": "Mat- och restavfall",
        }
    ]
    api.async_get_flex_dates = AsyncMock(return_value={"42": "2026-12-01"})
    api.async_get_contract_details.return_value = [{"UtilityName": "Elnät - Nätavtal"}]
    with (
        patch("custom_components.karlstadsenergi.KarlstadsenergiApi", return_value=api),
        patch("custom_components.karlstadsenergi._DataCache", _FakeCache),
        patch(
            "custom_components.karlstadsenergi._migrate_waste_unique_ids", new_callable=AsyncMock
        ),
        patch(
            "custom_components.karlstadsenergi.async_track_time_interval", return_value=MagicMock()
        ) as heartbeat,
        patch.object(
            KarlstadsenergiSpotPriceCoordinator, "_async_update_data", AsyncMock(return_value={})
        ),
        patch(
            "custom_components.karlstadsenergi._UtilityConsumptionCoordinator._async_import_consumption_statistics",
            new_callable=AsyncMock,
        ) as statistics,
        patch(
            "custom_components.karlstadsenergi._UtilityConsumptionCoordinator._async_import_fee_statistics",
            new_callable=AsyncMock,
        ) as fees,
    ):
        yield SimpleNamespace(
            hass=hass, api=api, heartbeat=heartbeat, statistics=statistics, fees=fees
        )


def test_single_resolver_legacy_and_precedence() -> None:
    assert all(resolve_features({}, {}).values())
    assert resolve_features(NEW_FEATURE_DEFAULTS, {}) == selections(CONF_WASTE)
    assert resolve_features(NEW_FEATURE_DEFAULTS, selections(CONF_SPOT)) == selections(CONF_SPOT)


@pytest.mark.asyncio
async def test_initial_defaults_and_all_off() -> None:
    flow = _make_flow()
    form = await flow.async_step_user()
    assert resolve_features(form["data_schema"]({}), {}) == selections(CONF_WASTE)
    result = await flow.async_step_user(selections())
    assert result["errors"] == {"base": "no_features"}


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", FEATURE_KEYS)
async def test_each_category_independent(setup_environment: SimpleNamespace, enabled: str) -> None:
    env = setup_environment
    entry = _make_entry(options=selections(enabled))
    assert await async_setup_entry(env.hass, entry)
    runtime = entry.runtime_data
    assert [getattr(runtime, attr) is not None for attr in COORDINATORS] == [
        key == enabled for key in FEATURE_KEYS
    ]
    created = []

    def add(entities, **kwargs):
        created.extend(entities)

    for platform in (sensor, calendar, binary_sensor):
        await platform.async_setup_entry(env.hass, entry, add)
    assert created
    coord = getattr(runtime, COORDINATORS[FEATURE_KEYS.index(enabled)])
    assert all(entity.coordinator is coord for entity in created)
    await coord.async_refresh()
    await coord.async_request_refresh()
    if enabled in (CONF_WASTE, CONF_SPOT):
        with patch(
            "custom_components.karlstadsenergi.dt_util.utcnow",
            return_value=datetime.now(UTC) + timedelta(days=2),
        ):
            await coord.async_refresh()
    diagnostics = await async_get_config_entry_diagnostics(env.hass, entry)
    assert diagnostics
    if enabled != CONF_WASTE:
        env.api.async_get_flex_services.assert_not_awaited()
        env.api.async_get_next_flex_dates.assert_not_awaited()
    if enabled in (CONF_WASTE, CONF_SPOT):
        env.api.async_get_consumption.assert_not_awaited()
        env.api.async_get_consumption_with_model.assert_not_awaited()
    if enabled != CONF_DISTRICT_HEATING:
        env.api.async_get_consumption_with_model.assert_not_awaited()
    if enabled != CONF_CONTRACTS:
        env.api.async_get_contract_details.assert_not_awaited()
    if enabled != CONF_SPOT:
        KarlstadsenergiSpotPriceCoordinator._async_update_data.assert_not_awaited()
    if enabled in (CONF_WASTE, CONF_SPOT, CONF_CONTRACTS):
        env.api.async_get_hourly_consumption.assert_not_awaited()
        env.api.async_get_monthly_consumption.assert_not_awaited()
        env.api.async_get_fee_consumption.assert_not_awaited()
        env.statistics.assert_not_awaited()
        env.fees.assert_not_awaited()
    if enabled == CONF_DISTRICT_HEATING:
        for method in (
            env.api.async_get_hourly_consumption,
            env.api.async_get_fee_consumption,
            env.api.async_get_monthly_consumption,
            env.api.async_get_consumption_with_model,
        ):
            assert all(call.args[0]["UtilityId"] == "F" for call in method.await_args_list)
    if enabled == CONF_SPOT:
        env.heartbeat.assert_not_called()
        env.api.authenticate.assert_not_awaited()
    else:
        env.heartbeat.assert_called_once()
    if enabled in (CONF_CONTRACTS, CONF_DISTRICT_HEATING):
        assert runtime.discovery._update_interval == timedelta(
            hours=24 if enabled == CONF_CONTRACTS else 1
        )
        env.api.async_get_consumption.assert_awaited_once()
        assert (
            runtime.discovery.model
            == env.api.async_get_consumption.return_value["ConsumptionModel"]
        )
        assert not hasattr(runtime.discovery, "data")
    assert await async_unload_entry(env.hass, entry)


@pytest.mark.asyncio
@pytest.mark.parametrize("electricity", [False, True])
async def test_shared_discovery_no_duplicate_requests(
    setup_environment: SimpleNamespace, electricity: bool
) -> None:
    env = setup_environment
    enabled = [CONF_DISTRICT_HEATING, CONF_CONTRACTS]
    if electricity:
        enabled.append(CONF_ELECTRICITY)
    entry = _make_entry(options=selections(*enabled))
    await async_setup_entry(env.hass, entry)
    env.api.async_get_consumption.assert_awaited_once()
    env.api.async_get_contract_details.assert_awaited_once_with(["site-99"])
    assert (
        entry.runtime_data.district_heating_coordinator.discovery
        is entry.runtime_data.contract_coordinator.discovery
    )
    assert env.statistics.await_count == (2 if electricity else 1)
    assert env.fees.await_count == (2 if electricity else 1)


@pytest.mark.asyncio
async def test_disabled_cache_cannot_hide_waste_startup_failure(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    env.api.async_get_flex_services.return_value = []
    env.api.async_get_next_flex_dates.side_effect = KarlstadsenergiConnectionError("offline")
    cached = {
        f"{DOMAIN}_{name}": {"data": {"old": True}}
        for name in ("consumption", "district_heating", "contracts", "spot_price")
    }
    with (
        patch.object(_FakeCache, "async_load", AsyncMock(return_value=cached)),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(env.hass, _make_entry(options=selections(CONF_WASTE)))
    env.api.async_get_consumption.assert_not_awaited()


@pytest.mark.asyncio
async def test_populated_disabled_cache_and_reload_are_inert(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    cached = {
        f"{DOMAIN}_{name}": {"data": {"old": True}}
        for name in ("consumption", "district_heating", "contracts", "spot_price")
    }
    entry = _make_entry(options=selections(CONF_WASTE))
    with patch.object(_FakeCache, "async_load", AsyncMock(return_value=cached)):
        for _ in range(2):
            await async_setup_entry(env.hass, entry)
            assert all(getattr(entry.runtime_data, attr) is None for attr in COORDINATORS[1:])
            await entry.runtime_data.waste_coordinator.async_refresh()
            await async_unload_entry(env.hass, entry)
    env.api.async_get_consumption.assert_not_awaited()
    env.api.async_get_contract_details.assert_not_awaited()
    env.statistics.assert_not_awaited()
    env.fees.assert_not_awaited()


@pytest.mark.asyncio
async def test_options_preserve_settings_and_reject_all_off() -> None:
    entry = _make_entry(
        options={**selections(CONF_WASTE), CONF_UPDATE_INTERVAL: 12, CONF_HISTORY_YEARS: 7}
    )
    flow = KarlstadsenergiOptionsFlow()
    flow.hass = _make_hass()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.handler = entry.entry_id
    result = await flow.async_step_init(selections())
    assert result["errors"] == {"base": "no_features"}
    result = await flow.async_step_init(selections(CONF_CONTRACTS))
    assert result["data"] == {
        **selections(CONF_CONTRACTS),
        CONF_UPDATE_INTERVAL: 12,
        CONF_HISTORY_YEARS: 7,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("bankid", [False, True])
async def test_initial_auth_explicit_selection_and_no_disabled_waste_validation(
    bankid: bool,
) -> None:
    flow = _make_flow()
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None
    form = await flow.async_step_user()
    submitted = form["data_schema"](
        {**selections(CONF_CONTRACTS), "auth_method": "bankid" if bankid else "password"}
    )
    await flow.async_step_user(submitted)
    api = _mock_password_api()
    if bankid:
        api.bankid_login = AsyncMock()
        flow._api = api
        flow._personnummer = "199001011234"
        flow._bankid_init = {"transaction_id": "test"}
        result = await flow._do_bankid_login({"customer_id": "id", "customer_code": "123"})
    else:
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi", return_value=api
        ):
            result = await flow.async_step_password(
                {"customer_number": "123", "password": "secret"}
            )
    assert resolve_features(result["data"], {}) == selections(CONF_CONTRACTS)
    api.async_get_next_flex_dates.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bankid", [False, True])
async def test_reauth_preserves_data_options_and_switches(bankid: bool) -> None:
    flow = _make_flow(source="reauth")
    entry = _make_entry(
        data={"personnummer": "199001011234", **selections(CONF_WASTE)},
        options={**selections(CONF_SPOT), CONF_HISTORY_YEARS: 7},
    )
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    await flow.async_step_reauth(entry.data)
    assert flow._features == selections(CONF_SPOT)
    api = _mock_password_api()
    with patch.object(flow, "async_update_and_abort", return_value={"type": "abort"}) as update:
        if bankid:
            api.bankid_login = AsyncMock()
            flow._api = api
            flow._bankid_init = {"transaction_id": "test"}
            await flow._do_bankid_login({"customer_id": "id", "customer_code": "123"})
        else:
            with patch(
                "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi", return_value=api
            ):
                await flow.async_step_password({"customer_number": "123", "password": "secret"})
        assert resolve_features(update.call_args.kwargs["data"], entry.options) == selections(
            CONF_SPOT
        )
        assert entry.options[CONF_HISTORY_YEARS] == 7
        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(entry.entry_id)
    api.async_get_next_flex_dates.assert_not_awaited()


@pytest.mark.asyncio
async def test_reauth_method_switch_drops_old_credentials() -> None:
    """Password -> BankID at reauth must not keep the stored password."""
    flow = _make_flow(source="reauth")
    entry = _make_entry(
        data={
            "personnummer": "123",
            "auth_method": "password",
            "password": "secret",
            **selections(CONF_WASTE, CONF_ELECTRICITY),
        },
    )
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    await flow.async_step_reauth(entry.data)
    api = _mock_password_api()
    api.bankid_login = AsyncMock()
    flow._api = api
    flow._bankid_init = {"transaction_id": "test"}
    with patch.object(flow, "async_update_and_abort", return_value={"type": "abort"}) as update:
        await flow._do_bankid_login({"customer_id": "id", "customer_code": "123"})

    data = update.call_args.kwargs["data"]
    assert data["auth_method"] == "bankid"
    assert "password" not in data
    # The category switches stored in data survive.
    assert resolve_features(data, {}) == selections(CONF_WASTE, CONF_ELECTRICITY)


@pytest.mark.asyncio
async def test_disable_shutdown_and_reenable_keep_ids(setup_environment: SimpleNamespace) -> None:
    env = setup_environment
    entry = _make_entry(options=selections(CONF_ELECTRICITY))
    await async_setup_entry(env.hass, entry)
    old = entry.runtime_data.consumption_coordinator
    entry.async_on_unload(old.async_add_listener(MagicMock()))
    entities = []
    await sensor.async_setup_entry(env.hass, entry, lambda new, **kwargs: entities.extend(new))
    ids = [entity.unique_id for entity in entities]
    await async_unload_entry(env.hass, entry)
    # Simulate HA's entry-scoped unload callbacks (including coordinator shutdown).
    for call in entry.async_on_unload.call_args_list:
        result = call.args[0]()
        if inspect.isawaitable(result):
            await result
    assert old._shutdown_requested
    assert old._unsub_refresh is None
    calls = env.api.async_get_consumption.await_count
    statistic_calls = env.statistics.await_count
    await old.async_refresh()
    assert env.api.async_get_consumption.await_count == calls
    assert env.statistics.await_count == statistic_calls
    env.heartbeat.return_value.assert_called_once()
    entry.async_on_unload.reset_mock()
    entry.options = selections(CONF_WASTE)
    env.hass.config_entries.async_reload = AsyncMock()
    await _async_reload_entry(env.hass, entry)
    env.hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
    await async_setup_entry(env.hass, entry)
    await entry.runtime_data.waste_coordinator.async_refresh()
    assert env.api.async_get_consumption.await_count == calls
    assert entry.runtime_data.consumption_coordinator is None
    await async_unload_entry(env.hass, entry)
    for call in reversed(entry.async_on_unload.call_args_list):
        result = call.args[0]()
        if inspect.isawaitable(result):
            await result
    entry.async_on_unload.reset_mock()
    entry.options = selections(CONF_ELECTRICITY)
    await async_setup_entry(env.hass, entry)
    new_entities = []
    await sensor.async_setup_entry(env.hass, entry, lambda new, **kwargs: new_entities.extend(new))
    assert [entity.unique_id for entity in new_entities] == ids
    await async_unload_entry(env.hass, entry)
    for call in reversed(entry.async_on_unload.call_args_list):
        result = call.args[0]()
        if inspect.isawaitable(result):
            await result


@pytest.mark.asyncio
@pytest.mark.parametrize("electricity", [False, True])
async def test_discovery_metadata_changes_recover_without_reload(
    setup_environment: SimpleNamespace,
    electricity: bool,
) -> None:
    env = setup_environment
    updated = deepcopy(env.api.async_get_consumption.return_value)
    initial = deepcopy(updated)
    initial["ConsumptionModel"]["SelectedSiteGroupNode"] = {"Utilities": []}
    env.api.async_get_consumption.return_value = initial
    enabled = [CONF_DISTRICT_HEATING, CONF_CONTRACTS]
    if electricity:
        enabled.append(CONF_ELECTRICITY)
    entry = _make_entry(options=selections(*enabled))
    await async_setup_entry(env.hass, entry)
    runtime = entry.runtime_data
    assert not runtime.district_heating_coordinator.data["available"]
    updated["ConsumptionModel"]["SiteId"] = "new-site"
    env.api.async_get_consumption.return_value = updated
    before = env.api.async_get_consumption.await_count
    with patch(
        "custom_components.karlstadsenergi.dt_util.utcnow",
        return_value=datetime.now(UTC) + timedelta(days=2),
    ):
        if electricity:
            await runtime.consumption_coordinator.async_refresh()
        await asyncio.gather(
            runtime.district_heating_coordinator.async_refresh(),
            runtime.contract_coordinator.async_refresh(),
        )
    assert runtime.district_heating_coordinator.data["available"]
    env.api.async_get_contract_details.assert_awaited_with(["new-site"])
    assert env.api.async_get_consumption.await_count == before + 1
    assert env.api.async_get_consumption_with_model.call_args.args[0]["SiteId"] == "new-site"


@pytest.mark.asyncio
@pytest.mark.parametrize("electricity", [False, True])
@pytest.mark.parametrize("failure", ["error", "empty"])
async def test_initial_discovery_failure_recovers(
    setup_environment: SimpleNamespace,
    electricity: bool,
    failure: str,
) -> None:
    env = setup_environment
    response = env.api.async_get_consumption.return_value
    if failure == "error":
        env.api.async_get_consumption.side_effect = KarlstadsenergiConnectionError("offline")
    else:
        env.api.async_get_consumption.return_value = {}
    enabled = [CONF_DISTRICT_HEATING, CONF_CONTRACTS]
    if electricity:
        enabled.append(CONF_ELECTRICITY)
    entry = _make_entry(options=selections(*enabled))
    await async_setup_entry(env.hass, entry)
    runtime = entry.runtime_data
    assert not (runtime.district_heating_coordinator.data or {}).get("available")
    before = env.api.async_get_consumption.await_count
    env.api.async_get_consumption.side_effect = None
    env.api.async_get_consumption.return_value = response
    if electricity:
        # Dependent categories never initiate extra electricity collection.
        assert before == 1
        await runtime.district_heating_coordinator.async_refresh()
        assert env.api.async_get_consumption.await_count == before
        await runtime.consumption_coordinator.async_refresh()
    await asyncio.gather(
        runtime.district_heating_coordinator.async_refresh(),
        runtime.contract_coordinator.async_refresh(),
    )
    assert runtime.district_heating_coordinator.data["available"]
    env.api.async_get_contract_details.assert_awaited_with(["site-99"])
    assert env.api.async_get_consumption.await_count == before + 1


_SITE_CELLS = [
    (prev, this, fails, slice_)
    for prev in (True, False)
    for this in (True, False)
    for fails in (False, True)
    # A missing site slice means an entry from before the slice existed,
    # which always ran with electricity on.
    for slice_ in ((True, False) if prev else (True,))
]


async def _setup_and_collect_devices(env: SimpleNamespace, entry) -> dict[str, set]:
    """Set up the entry and sensor platform; return unique_id -> device identifiers."""
    await async_setup_entry(env.hass, entry)
    entities: list = []
    await sensor.async_setup_entry(env.hass, entry, lambda new, **kwargs: entities.extend(new))
    devices = {
        entity.unique_id: set(entity.device_info["identifiers"])
        for entity in entities
        if getattr(entity, "device_info", None)
    }
    await async_unload_entry(env.hass, entry)
    for call in reversed(entry.async_on_unload.call_args_list):
        result = call.args[0]()
        if inspect.isawaitable(result):
            await result
    return devices


def _site_options(electricity: bool) -> dict[str, bool]:
    enabled = [CONF_DISTRICT_HEATING, CONF_CONTRACTS, CONF_SPOT]
    if electricity:
        enabled.append(CONF_ELECTRICITY)
    return selections(*enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prev_electricity", "this_electricity", "fails", "has_slice"), _SITE_CELLS
)
async def test_site_device_identity_matrix(
    setup_environment: SimpleNamespace,
    prev_electricity: bool,
    this_electricity: bool,
    fails: bool,
    has_slice: bool,
) -> None:
    """Site-scoped entities keep their device across restarts and category changes.

    Electricity, heating, contract and spot entities x previous run with or
    without electricity x this run with or without electricity x first
    request ok or failing x site slice present or missing (legacy entry).
    """
    env = setup_environment
    store: dict = {}
    with patch("custom_components.karlstadsenergi._DataCache", _persistent_cache(store)):
        before = await _setup_and_collect_devices(
            env, _make_entry(options=_site_options(prev_electricity))
        )
        assert store[SITE_CACHE_KEY]["data"]["SiteId"] == "site-99"
        if not has_slice:
            del store[SITE_CACHE_KEY]
        if fails:
            env.api.async_get_consumption.side_effect = KarlstadsenergiConnectionError("offline")
        after = await _setup_and_collect_devices(
            env, _make_entry(options=_site_options(this_electricity))
        )

    common = before.keys() & after.keys()
    assert common
    for unique_id in common:
        assert after[unique_id] == before[unique_id], unique_id
    # Entities that are new in this run still land on the site device.
    for unique_id, identifiers in after.items():
        assert any("site-99" in identifier[1] for identifier in identifiers), unique_id


@pytest.mark.asyncio
async def test_new_install_without_known_site_uses_customer_devices(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    env.api.async_get_consumption.side_effect = KarlstadsenergiConnectionError("offline")
    with patch("custom_components.karlstadsenergi._DataCache", _persistent_cache({})):
        devices = await _setup_and_collect_devices(env, _make_entry(options=selections(CONF_SPOT)))

    assert devices
    for identifiers in devices.values():
        assert not any("site" in identifier[1] for identifier in identifiers)


@pytest.mark.asyncio
async def test_discovery_coalesces_overlapping_refreshes(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    entry = _make_entry(options=selections(CONF_DISTRICT_HEATING, CONF_CONTRACTS))
    await async_setup_entry(env.hass, entry)
    discovery = entry.runtime_data.discovery
    discovery._last_refresh = datetime.now(UTC) - timedelta(days=2)
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        started.set()
        await release.wait()
        return {"ConsumptionModel": {"SiteId": "changed"}}

    env.api.async_get_consumption.side_effect = fetch
    before = env.api.async_get_consumption.await_count
    first = asyncio.create_task(discovery.async_get_model())
    await started.wait()
    second = asyncio.create_task(discovery.async_get_model())
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    assert await asyncio.gather(first, second) == [{"SiteId": "changed"}] * 2
    assert env.api.async_get_consumption.await_count == before + 1


@pytest.mark.asyncio
async def test_new_entry_data_selection_survives_restart(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    entry = _make_entry(data={"personnummer": "123", **NEW_FEATURE_DEFAULTS})
    for _ in range(2):
        await async_setup_entry(env.hass, entry)
        assert entry.runtime_data.waste_coordinator is not None
        assert all(getattr(entry.runtime_data, attr) is None for attr in COORDINATORS[1:])
        await async_unload_entry(env.hass, entry)
    env.api.async_get_consumption.assert_not_awaited()
    env.api.async_get_contract_details.assert_not_awaited()


def test_switch_translations_are_complete() -> None:
    from pathlib import Path

    base = Path(__file__).parents[1] / "custom_components" / DOMAIN
    strings = json.loads((base / "strings.json").read_text())
    for path in (
        base / "strings.json",
        base / "translations/en.json",
        base / "translations/sv.json",
    ):
        translated = json.loads(path.read_text())
        for section, step in (("config", "user"), ("options", "init")):
            assert set(FEATURE_KEYS) <= translated[section]["step"][step]["data"].keys()
            assert translated[section]["error"]["no_features"]
        if path.name == "en.json":
            assert translated == strings


@pytest.mark.asyncio
async def test_waste_only_auth_failure_keeps_cached_entities(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    waste = {
        "services": env.api.async_get_flex_services.return_value,
        "dates": {"42": "2026-12-01"},
        "next_dates": [],
    }
    cached = {f"{DOMAIN}_waste": {"data": waste}}
    env.api.async_get_flex_services.side_effect = KarlstadsenergiAuthError("expired")
    entry = _make_entry(options=selections(CONF_WASTE))
    with patch.object(_FakeCache, "async_load", AsyncMock(return_value=cached)):
        await async_setup_entry(env.hass, entry)
    assert entry.runtime_data.waste_coordinator.data == waste
    assert not entry.runtime_data.waste_coordinator.last_update_success
    created = []
    for platform in (sensor, calendar, binary_sensor):
        await platform.async_setup_entry(env.hass, entry, lambda new, **kwargs: created.extend(new))
    assert len(created) == 3
    assert all(entity.available for entity in created)
    env.api.async_get_consumption.assert_not_awaited()
    env.api.async_get_contract_details.assert_not_awaited()
    env.statistics.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_task_belongs_to_entry(setup_environment: SimpleNamespace) -> None:
    from datetime import UTC, datetime

    env = setup_environment
    entry = _make_entry(options=selections(CONF_WASTE))
    await async_setup_entry(env.hass, entry)
    env.heartbeat.call_args.args[1](datetime.now(UTC))
    entry.async_create_background_task.assert_called_once()
    # Execute the captured coroutine without starting a live HA scheduler.
    await entry.async_create_background_task.call_args.args[1]
    env.api.async_heartbeat.assert_awaited_once()


@pytest.mark.asyncio
async def test_spot_only_password_entry_does_not_authenticate_at_startup(
    setup_environment: SimpleNamespace,
) -> None:
    env = setup_environment
    entry = _make_entry(
        data={
            "personnummer": "123",
            "auth_method": "password",
            "password": "secret",
            **selections(CONF_SPOT),
        }
    )
    await async_setup_entry(env.hass, entry)
    env.api.authenticate.assert_not_awaited()
    env.api.async_get_consumption.assert_not_awaited()
    env.api.async_get_next_flex_dates.assert_not_awaited()
    env.heartbeat.assert_not_called()


@pytest.mark.asyncio
async def test_partial_legacy_options_roundtrip() -> None:
    entry = _make_entry(options={CONF_ELECTRICITY: False, CONF_UPDATE_INTERVAL: 12})
    flow = KarlstadsenergiOptionsFlow()
    flow.hass = _make_hass()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.handler = entry.entry_id
    form = await flow.async_step_init()
    submitted = form["data_schema"]({})
    assert resolve_features({}, submitted) == {key: key != CONF_ELECTRICITY for key in FEATURE_KEYS}
    result = await flow.async_step_init(submitted)
    assert resolve_features({}, result["data"]) == resolve_features({}, entry.options)
    assert result["data"][CONF_UPDATE_INTERVAL] == 12
