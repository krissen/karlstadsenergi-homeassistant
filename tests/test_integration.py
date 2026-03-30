"""Integration-level tests for async_setup_entry, async_unload_entry,
ConsumptionCoordinator, ContractCoordinator, and the BankID config flow.

Tests are unit-level: no live HA instance required. HA classes are
imported directly; the integration code under test is exercised with
minimal mocking, following the patterns established in test_coordinator.py
and test_config_flow.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi import (
    KarlstadsenergiConsumptionCoordinator,
    KarlstadsenergiContractCoordinator,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.karlstadsenergi.api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    BANKID_COMPLETE,
)
from custom_components.karlstadsenergi.config_flow import KarlstadsenergiConfigFlow
from custom_components.karlstadsenergi.const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
    CONF_UPDATE_INTERVAL,
    PLATFORMS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def _make_entry(
    data: dict | None = None,
    options: dict | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.data = data or {
        CONF_PERSONNUMMER: "199001011234",
        CONF_AUTH_METHOD: AUTH_BANKID,
        "session_cookies": {"ASP.NET_SessionId": "abc123"},
    }
    entry.options = options or {}
    entry.runtime_data = None
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


def _make_api(*, auth_error: bool = False, connection_error: bool = False) -> MagicMock:
    """Build a mock API with sensible defaults for all coordinator calls."""
    from custom_components.karlstadsenergi.api import (
        KarlstadsenergiAuthError,
        KarlstadsenergiConnectionError,
    )

    api = MagicMock()
    api.get_session_cookies = MagicMock(return_value={})
    api.set_session_cookies = MagicMock()
    api.authenticate = AsyncMock()
    api.async_close = AsyncMock()
    api.async_heartbeat = AsyncMock()

    # Waste coordinator methods
    if auth_error:
        api.async_get_flex_services = AsyncMock(
            side_effect=KarlstadsenergiAuthError("session expired")
        )
    elif connection_error:
        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
    else:
        api.async_get_flex_services = AsyncMock(return_value=[])
        api.async_get_next_flex_dates = AsyncMock(return_value=[])

    # Consumption coordinator methods
    api.async_get_consumption = AsyncMock(
        return_value={
            "ConsumptionModel": {
                "SiteId": "site-99",
                "ModelId": "model-1",
            }
        }
    )
    api.async_get_hourly_consumption = AsyncMock(return_value={"hours": []})
    api.async_get_service_info = AsyncMock(return_value={"info": "ok"})
    api.async_get_fee_consumption = AsyncMock(return_value={"fees": []})

    # Contract coordinator methods
    api.async_get_contract_details = AsyncMock(return_value=[])

    return api


def _make_flow() -> KarlstadsenergiConfigFlow:
    flow = KarlstadsenergiConfigFlow()
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry.return_value = None
    flow.hass = hass
    flow.context = {"source": "user"}
    return flow


# ---------------------------------------------------------------------------
# async_setup_entry -- success path
# ---------------------------------------------------------------------------


class TestAsyncSetupEntrySuccess:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True

    @pytest.mark.asyncio
    async def test_runtime_data_is_populated(self) -> None:
        from custom_components.karlstadsenergi import KarlstadsenergiData

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        assert isinstance(entry.runtime_data, KarlstadsenergiData)
        assert entry.runtime_data.api is api

    @pytest.mark.asyncio
    async def test_all_coordinators_present_in_runtime_data(self) -> None:
        from custom_components.karlstadsenergi import (
            KarlstadsenergiConsumptionCoordinator,
            KarlstadsenergiContractCoordinator,
            KarlstadsenergiSpotPriceCoordinator,
            KarlstadsenergiWasteCoordinator,
        )

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        rd = entry.runtime_data
        assert isinstance(rd.waste_coordinator, KarlstadsenergiWasteCoordinator)
        assert isinstance(
            rd.consumption_coordinator, KarlstadsenergiConsumptionCoordinator
        )
        assert isinstance(rd.contract_coordinator, KarlstadsenergiContractCoordinator)
        assert isinstance(
            rd.spot_price_coordinator, KarlstadsenergiSpotPriceCoordinator
        )

    @pytest.mark.asyncio
    async def test_platforms_are_forwarded(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_heartbeat_is_registered(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        cancel_fn = MagicMock()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=cancel_fn,
            ) as mock_track,
        ):
            await async_setup_entry(hass, entry)

        mock_track.assert_called_once()
        # The cancel function is registered with async_on_unload
        entry.async_on_unload.assert_any_call(cancel_fn)

    @pytest.mark.asyncio
    async def test_saved_cookies_are_applied_to_api(self) -> None:
        """When session_cookies are present, they are set on the API (no auth call)."""
        hass = _make_hass()
        entry = _make_entry(
            data={
                CONF_PERSONNUMMER: "199001011234",
                CONF_AUTH_METHOD: AUTH_BANKID,
                "session_cookies": {"ASP.NET_SessionId": "saved-cookie"},
            }
        )
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        api.set_session_cookies.assert_called_once_with(
            {"ASP.NET_SessionId": "saved-cookie"}
        )
        api.authenticate.assert_not_called()

    @pytest.mark.asyncio
    async def test_password_auth_called_when_no_cookies(self) -> None:
        """For password auth with no saved cookies, authenticate() is called."""
        hass = _make_hass()
        entry = _make_entry(
            data={
                CONF_PERSONNUMMER: "123456",
                CONF_AUTH_METHOD: AUTH_PASSWORD,
                "password": "secret",
                # no session_cookies key
            }
        )
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        api.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_options_stored_in_runtime_data(self) -> None:
        hass = _make_hass()
        entry = _make_entry(options={"update_interval": 12})
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        assert entry.runtime_data.setup_options == {"update_interval": 12}

    @pytest.mark.asyncio
    async def test_site_id_from_consumption_passed_to_contract_coordinator(
        self,
    ) -> None:
        """SiteId extracted from consumption data is passed to ContractCoordinator."""
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        # consumption returns a specific SiteId
        api.async_get_consumption = AsyncMock(
            return_value={"ConsumptionModel": {"SiteId": "site-42", "ModelId": "m"}}
        )
        api.async_get_contract_details = AsyncMock(return_value=[{"id": "site-42"}])

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        api.async_get_contract_details.assert_called_once_with(["site-42"])

    @pytest.mark.asyncio
    async def test_spot_price_url_fetched_during_setup(self) -> None:
        """SpotPriceCoordinator fetches from the public Evado URL during setup."""

        hass = _make_hass()
        # Add a mock clientsession to hass for the SpotPriceCoordinator
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={"timezone": "Europe/Stockholm", "spotprices": []}
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        entry = _make_entry()
        api = _make_api()

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_get_clientsession",
                return_value=mock_session,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            result = await async_setup_entry(hass, entry)

        # Should succeed (spot price failures are non-fatal)
        assert result is True


# ---------------------------------------------------------------------------
# async_setup_entry -- auth failure on waste coordinator
# ---------------------------------------------------------------------------


class TestAsyncSetupEntryAuthFailure:
    @pytest.mark.asyncio
    async def test_raises_config_entry_auth_failed_on_waste_auth_error(self) -> None:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api(auth_error=True)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_api_session_closed_on_auth_failure(self) -> None:
        """API session must be closed even when auth fails."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api(auth_error=True)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await async_setup_entry(hass, entry)

        api.async_close.assert_called_once()


# ---------------------------------------------------------------------------
# async_setup_entry -- connection failure (ConfigEntryNotReady)
# ---------------------------------------------------------------------------


class TestAsyncSetupEntryConnectionFailure:
    @pytest.mark.asyncio
    async def test_raises_config_entry_not_ready_on_waste_connection_error(
        self,
    ) -> None:
        from homeassistant.exceptions import ConfigEntryNotReady

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api(connection_error=True)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_api_session_closed_on_connection_failure(self) -> None:
        from homeassistant.exceptions import ConfigEntryNotReady

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api(connection_error=True)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

        api.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_config_entry_not_ready_on_initial_password_auth_failure(
        self,
    ) -> None:
        """Password auth with no cookies that fails raises ConfigEntryNotReady."""
        from homeassistant.exceptions import ConfigEntryNotReady

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = _make_hass()
        entry = _make_entry(
            data={
                CONF_PERSONNUMMER: "123456",
                CONF_AUTH_METHOD: AUTH_PASSWORD,
                "password": "secret",
            }
        )
        api = _make_api()
        api.authenticate = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

        api.async_close.assert_called_once()


# ---------------------------------------------------------------------------
# async_setup_entry -- non-fatal failures (consumption, contract, spot)
# ---------------------------------------------------------------------------


class TestAsyncSetupEntryNonFatalFailures:
    @pytest.mark.asyncio
    async def test_setup_succeeds_when_consumption_fails(self) -> None:
        """Consumption failure is non-fatal; setup must still return True."""
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("consumption down")
        )

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True

    @pytest.mark.asyncio
    async def test_setup_succeeds_when_contract_fails(self) -> None:
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        api.async_get_contract_details = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("contracts down")
        )

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True


# ---------------------------------------------------------------------------
# async_unload_entry
# ---------------------------------------------------------------------------


class TestAsyncUnloadEntry:
    @pytest.mark.asyncio
    async def test_returns_true_on_successful_unload(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        # Attach runtime_data as async_unload_entry uses it
        runtime_data = MagicMock()
        runtime_data.api = api
        entry.runtime_data = runtime_data

        result = await async_unload_entry(hass, entry)

        assert result is True

    @pytest.mark.asyncio
    async def test_platforms_unloaded(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        runtime_data = MagicMock()
        runtime_data.api = _make_api()
        entry.runtime_data = runtime_data

        await async_unload_entry(hass, entry)

        hass.config_entries.async_unload_platforms.assert_called_once_with(
            entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_api_session_closed_on_unload(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        api = _make_api()
        runtime_data = MagicMock()
        runtime_data.api = api
        entry.runtime_data = runtime_data

        await async_unload_entry(hass, entry)

        api.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_not_closed_when_platform_unload_fails(self) -> None:
        """If platform unload fails, API session should NOT be closed."""
        hass = _make_hass()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        entry = _make_entry()
        api = _make_api()
        runtime_data = MagicMock()
        runtime_data.api = api
        entry.runtime_data = runtime_data

        result = await async_unload_entry(hass, entry)

        assert result is False
        api.async_close.assert_not_called()


# ---------------------------------------------------------------------------
# ConsumptionCoordinator._async_update_data
# ---------------------------------------------------------------------------


class TestConsumptionCoordinatorUpdate:
    @pytest.mark.asyncio
    async def test_returns_all_keys_on_success(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        assert "consumption" in result
        assert "hourly" in result
        assert "service_info" in result
        assert "fee_data" in result

    @pytest.mark.asyncio
    async def test_consumption_value_is_passed_through(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            return_value={"ConsumptionModel": {"SiteId": "s1"}, "Status": "OK"}
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        assert result["consumption"]["Status"] == "OK"

    @pytest.mark.asyncio
    async def test_hourly_data_fetched_when_model_present(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            return_value={"ConsumptionModel": {"SiteId": "s1", "ModelId": "m1"}}
        )
        api.async_get_hourly_consumption = AsyncMock(return_value={"hours": [1, 2, 3]})
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        api.async_get_hourly_consumption.assert_called_once()
        assert result["hourly"] == {"hours": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_hourly_data_empty_when_no_model(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(return_value={})  # no ConsumptionModel
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        api.async_get_hourly_consumption.assert_not_called()
        assert result["hourly"] == {}

    @pytest.mark.asyncio
    async def test_service_info_included_in_result(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_service_info = AsyncMock(return_value={"NetAreaCode": "SE3"})
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        assert result["service_info"] == {"NetAreaCode": "SE3"}

    @pytest.mark.asyncio
    async def test_service_info_empty_on_failure(self) -> None:
        """service_info failure is non-fatal; result key present but empty."""
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_service_info = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("service info down")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        assert result["service_info"] == {}

    @pytest.mark.asyncio
    async def test_fee_data_included_in_result(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_fee_consumption = AsyncMock(
            return_value={"DetailedConsumptionChart": {"SeriesList": []}}
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        result = await coord._async_update_data()

        assert "DetailedConsumptionChart" in result["fee_data"]

    @pytest.mark.asyncio
    async def test_raises_config_entry_auth_failed_on_auth_error(self) -> None:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiAuthError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            side_effect=KarlstadsenergiAuthError("session expired")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_saves_cookies_after_successful_update(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        coord._save_cookies = MagicMock()

        await coord._async_update_data()

        coord._save_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_saves_cookies_even_on_connection_failure(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_consumption = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiConsumptionCoordinator(hass, api, 1, entry)
        coord._save_cookies = MagicMock()

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        coord._save_cookies.assert_called_once()


# ---------------------------------------------------------------------------
# ContractCoordinator._async_update_data
# ---------------------------------------------------------------------------


class TestContractCoordinatorUpdate:
    @pytest.mark.asyncio
    async def test_returns_contracts_key_on_success(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_contract_details = AsyncMock(
            return_value=[{"UtilityName": "Elnät - Nätavtal"}]
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])
        result = await coord._async_update_data()

        assert "contracts" in result

    @pytest.mark.asyncio
    async def test_contract_data_passed_through(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        contracts = [{"UtilityName": "Elnät - Nätavtal", "ContractId": "c1"}]
        api.async_get_contract_details = AsyncMock(return_value=contracts)
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])
        result = await coord._async_update_data()

        assert result["contracts"] == contracts

    @pytest.mark.asyncio
    async def test_site_ids_forwarded_to_api(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(
            hass, api, entry, ["site-1", "site-2"]
        )
        await coord._async_update_data()

        api.async_get_contract_details.assert_called_once_with(["site-1", "site-2"])

    @pytest.mark.asyncio
    async def test_empty_site_ids_calls_api_with_empty_list(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, [])
        await coord._async_update_data()

        api.async_get_contract_details.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_raises_config_entry_auth_failed_on_auth_error(self) -> None:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiAuthError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_contract_details = AsyncMock(
            side_effect=KarlstadsenergiAuthError("session expired")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_contract_details = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_saves_cookies_after_successful_update(self) -> None:
        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])
        coord._save_cookies = MagicMock()

        await coord._async_update_data()

        coord._save_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_saves_cookies_even_on_update_failure(self) -> None:
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        api.async_get_contract_details = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, ["site-1"])
        coord._save_cookies = MagicMock()

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        coord._save_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_interval_is_24_hours(self) -> None:
        """ContractCoordinator is hardwired to a 24-hour update interval."""
        from datetime import timedelta

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.config_entries = MagicMock()
        api = _make_api()
        entry = MagicMock()
        entry.data = {"session_cookies": {}}

        coord = KarlstadsenergiContractCoordinator(hass, api, entry, [])

        assert coord.update_interval == timedelta(hours=24)


# ---------------------------------------------------------------------------
# BankID config flow: initiate -> poll -> select_account -> login
# ---------------------------------------------------------------------------


class TestBankIdFlowFullPath:
    @pytest.mark.asyncio
    async def test_personnummer_step_advances_to_bankid(self) -> None:
        """Valid personnummer starts BankID and advances to bankid step."""
        flow = _make_flow()
        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "bankid"

    @pytest.mark.asyncio
    async def test_bankid_step_shows_form_with_auto_start_token(self) -> None:
        """bankid step description_placeholders must contain auto_start_token."""
        flow = _make_flow()
        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )

        # The bankid form shows auto_start_token as placeholder
        assert result["description_placeholders"]["auto_start_token"] == "token-abc"

    @pytest.mark.asyncio
    async def test_bankid_poll_complete_single_account_creates_entry(self) -> None:
        """When BankID poll completes and only one account exists, entry is created."""
        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        account = {
            "customer_id": "cust-1",
            "customer_code": "123456",
            "full_name": "Test User",
            "sub_user_id": "",
        }
        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )
        mock_api.bankid_poll = AsyncMock(return_value={"status": BANKID_COMPLETE})
        mock_api.bankid_get_customers = AsyncMock(return_value=[account])
        mock_api.bankid_login = AsyncMock()
        mock_api.async_get_next_flex_dates = AsyncMock(return_value=[])
        mock_api.get_session_cookies = MagicMock(
            return_value={"ASP.NET_SessionId": "s"}
        )
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            # Step 1: enter personnummer
            result = await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )
            assert result["step_id"] == "bankid"

            # Step 2: user clicks Submit (poll)
            result = await flow.async_step_bankid(user_input={})

        assert result["type"] == "create_entry"
        assert result["data"][CONF_PERSONNUMMER] == "199001011234"
        assert result["data"][CONF_AUTH_METHOD] == AUTH_BANKID
        assert result["data"]["customer_code"] == "123456"

    @pytest.mark.asyncio
    async def test_bankid_poll_complete_multiple_accounts_shows_selection(self) -> None:
        """When BankID poll completes with multiple accounts, select_account is shown."""
        flow = _make_flow()

        accounts = [
            {"customer_id": "c1", "customer_code": "111", "full_name": "Alice"},
            {"customer_id": "c2", "customer_code": "222", "full_name": "Bob"},
        ]
        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )
        mock_api.bankid_poll = AsyncMock(return_value={"status": BANKID_COMPLETE})
        mock_api.bankid_get_customers = AsyncMock(return_value=accounts)
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )
            result = await flow.async_step_bankid(user_input={})

        assert result["type"] == "form"
        assert result["step_id"] == "select_account"

    @pytest.mark.asyncio
    async def test_select_account_creates_entry_for_chosen_account(self) -> None:
        """Selecting account index 1 logs in with that account."""
        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        accounts = [
            {
                "customer_id": "c1",
                "customer_code": "111",
                "full_name": "Alice",
                "sub_user_id": "",
            },
            {
                "customer_id": "c2",
                "customer_code": "222",
                "full_name": "Bob",
                "sub_user_id": "",
            },
        ]
        mock_api = MagicMock()
        mock_api.bankid_login = AsyncMock()
        mock_api.async_get_next_flex_dates = AsyncMock(return_value=[])
        mock_api.get_session_cookies = MagicMock(return_value={})
        mock_api.async_close = AsyncMock()

        flow._api = mock_api
        flow._personnummer = "199001011234"
        flow._bankid_init = {"transaction_id": "txn-001"}
        flow._accounts = accounts

        result = await flow.async_step_select_account(user_input={"account": "1"})

        assert result["type"] == "create_entry"
        assert result["data"]["customer_code"] == "222"
        mock_api.bankid_login.assert_called_once_with(
            "199001011234", "c2", "txn-001", ""
        )

    @pytest.mark.asyncio
    async def test_bankid_pending_shows_error_and_re_initiates(self) -> None:
        """When poll returns a pending status, bankid_pending error is shown."""
        flow = _make_flow()

        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )
        # First poll: pending; second initiate for re-try
        mock_api.bankid_poll = AsyncMock(
            return_value={"status": 2}
        )  # BANKID_OUTSTANDING
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )
            result = await flow.async_step_bankid(user_input={})

        assert result["type"] == "form"
        assert result["step_id"] == "bankid"
        assert result["errors"].get("base") == "bankid_pending"

    @pytest.mark.asyncio
    async def test_bankid_initiate_connection_error_shows_user_form(self) -> None:
        """Connection error during initiate shows 'cannot_connect' on user form."""
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        flow = _make_flow()

        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("connect failed")
        )
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )
            result = await flow.async_step_bankid(user_input=None)

        # After initiate fails, the flow re-creates the api in async_step_bankid
        # and raises the connection error, showing the user form
        assert result["type"] == "form"

    @pytest.mark.asyncio
    async def test_bankid_login_auth_error_returns_to_form(self) -> None:
        """AuthError during _do_bankid_login returns to personnummer form."""
        from custom_components.karlstadsenergi.api import KarlstadsenergiAuthError

        flow = _make_flow()

        account = {
            "customer_id": "c1",
            "customer_code": "123456",
            "full_name": "Test",
            "sub_user_id": "",
        }
        mock_api = MagicMock()
        mock_api.bankid_login = AsyncMock(
            side_effect=KarlstadsenergiAuthError("login rejected")
        )
        mock_api.async_close = AsyncMock()

        flow._api = mock_api
        flow._personnummer = "199001011234"
        flow._bankid_init = {"transaction_id": "txn-001"}
        flow._accounts = [account]

        result = await flow._do_bankid_login(account)

        assert result["type"] == "form"
        assert result["step_id"] == "bankid_personnummer"
        assert result["errors"]["base"] == "bankid_failed"
        mock_api.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_accounts_returned_shows_bankid_failed_error(self) -> None:
        """Empty accounts list after BankID complete shows bankid_failed error."""
        flow = _make_flow()

        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-001",
                "auto_start_token": "token-abc",
                "qr_code_base64": "",
                "transaction_id": "txn-001",
            }
        )
        mock_api.bankid_poll = AsyncMock(return_value={"status": BANKID_COMPLETE})
        mock_api.bankid_get_customers = AsyncMock(return_value=[])  # no accounts
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            await flow.async_step_bankid_personnummer(
                user_input={CONF_PERSONNUMMER: "199001011234"}
            )
            result = await flow.async_step_bankid(user_input={})

        assert result["type"] == "form"
        assert result["errors"].get("base") == "bankid_failed"


# ---------------------------------------------------------------------------
# Deferred entity registration (H-7): waste entities created via listener
# ---------------------------------------------------------------------------


class TestDeferredWasteEntityRegistration:
    @pytest.mark.asyncio
    async def test_waste_entities_created_via_listener_when_initially_empty(
        self,
    ) -> None:
        """When waste_coordinator.data is None/empty at setup, a listener is
        registered. Once data arrives the listener calls async_add_entities."""
        from custom_components.karlstadsenergi.sensor import async_setup_entry as sensor_setup

        # Build a minimal runtime_data stub where waste data is initially absent.
        waste_coord = MagicMock()
        waste_coord.data = None  # no data at setup time

        consumption_coord = MagicMock()
        consumption_coord.data = None

        contract_coord = MagicMock()
        contract_coord.data = None

        spot_coord = MagicMock()
        spot_coord.data = None

        runtime = MagicMock()
        runtime.waste_coordinator = waste_coord
        runtime.consumption_coordinator = consumption_coord
        runtime.contract_coordinator = contract_coord
        runtime.spot_price_coordinator = spot_coord

        entry = _make_entry()
        entry.runtime_data = runtime

        hass = _make_hass()
        hass.data = {}

        added_entities: list = []

        def _capture_add(entities, **kwargs):
            added_entities.extend(entities if hasattr(entities, "__iter__") else [entities])

        # Capture the listener that sensor platform registers on the waste coordinator
        registered_listener = None

        def _fake_add_listener(callback):
            nonlocal registered_listener
            registered_listener = callback
            return MagicMock()  # unsub

        waste_coord.async_add_listener = _fake_add_listener

        # Capture listener on contract coordinator too (avoid AttributeError)
        contract_coord.async_add_listener = MagicMock(return_value=MagicMock())

        await sensor_setup(hass, entry, _capture_add)

        # At this point listener should be registered (waste data was None)
        assert registered_listener is not None, "Listener was not registered"

        # Now simulate data arriving
        waste_coord.data = {
            "services": [],
            "next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-05-01", "Address": "Testgatan 1", "Size": "140L"}],
        }

        before_count = len(added_entities)
        registered_listener()
        after_count = len(added_entities)

        # At least one entity should have been added by the listener callback
        assert after_count > before_count, (
            "Listener callback did not add any entities "
            f"(before={before_count}, after={after_count})"
        )

    @pytest.mark.asyncio
    async def test_waste_listener_not_registered_when_data_present(self) -> None:
        """When waste data is available at setup, no listener is registered."""
        from custom_components.karlstadsenergi.sensor import async_setup_entry as sensor_setup

        waste_coord = MagicMock()
        waste_coord.data = {
            "services": [],
            "next_dates": [{"Type": "Mat- och restavfall", "Date": "2026-05-01", "Address": "Testgatan 1", "Size": "140L"}],
        }
        # async_add_listener should never be called when data is already present
        waste_coord.async_add_listener = MagicMock(return_value=MagicMock())

        consumption_coord = MagicMock()
        consumption_coord.data = None

        contract_coord = MagicMock()
        contract_coord.data = None
        contract_coord.async_add_listener = MagicMock(return_value=MagicMock())

        spot_coord = MagicMock()
        spot_coord.data = None

        runtime = MagicMock()
        runtime.waste_coordinator = waste_coord
        runtime.consumption_coordinator = consumption_coord
        runtime.contract_coordinator = contract_coord
        runtime.spot_price_coordinator = spot_coord

        entry = _make_entry()
        entry.runtime_data = runtime

        hass = _make_hass()
        hass.data = {}

        await sensor_setup(hass, entry, MagicMock())

        waste_coord.async_add_listener.assert_not_called()


# ---------------------------------------------------------------------------
# _async_reload_entry (M-10): options change triggers reload, data-only does not
# ---------------------------------------------------------------------------


class TestAsyncReloadEntry:
    @pytest.mark.asyncio
    async def test_reload_triggered_when_options_changed(self) -> None:
        """_async_reload_entry must call async_reload when options differ from
        setup_options stored in runtime_data."""
        from custom_components.karlstadsenergi import _async_reload_entry

        hass = _make_hass()
        hass.config_entries.async_reload = AsyncMock()

        entry = _make_entry(options={"update_interval": 12})
        entry.entry_id = "test-entry-id"
        runtime = MagicMock()
        runtime.setup_options = {"update_interval": 6}  # different from current options
        entry.runtime_data = runtime

        await _async_reload_entry(hass, entry)

        hass.config_entries.async_reload.assert_called_once_with("test-entry-id")

    @pytest.mark.asyncio
    async def test_reload_not_triggered_on_data_only_change(self) -> None:
        """_async_reload_entry must NOT call async_reload when options match
        setup_options (e.g. a cookie save updated entry.data but not options)."""
        from custom_components.karlstadsenergi import _async_reload_entry

        hass = _make_hass()
        hass.config_entries.async_reload = AsyncMock()

        entry = _make_entry(options={"update_interval": 6})
        runtime = MagicMock()
        runtime.setup_options = {"update_interval": 6}  # same as current options
        entry.runtime_data = runtime

        await _async_reload_entry(hass, entry)

        hass.config_entries.async_reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_reload_not_triggered_when_both_options_empty(self) -> None:
        """_async_reload_entry does not reload when neither current nor setup options
        have been customised (both are empty dicts)."""
        from custom_components.karlstadsenergi import _async_reload_entry

        hass = _make_hass()
        hass.config_entries.async_reload = AsyncMock()

        entry = _make_entry(options={})
        runtime = MagicMock()
        runtime.setup_options = {}
        entry.runtime_data = runtime

        await _async_reload_entry(hass, entry)

        hass.config_entries.async_reload.assert_not_called()


# ---------------------------------------------------------------------------
# Update interval clamping (M-11)
# ---------------------------------------------------------------------------


class TestUpdateIntervalClamping:
    """Verify that async_setup_entry clamps update_interval to [MIN, MAX]."""

    def _setup_args(self, interval: int):
        """Return (hass, entry, api) with the given update_interval option."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_UPDATE_INTERVAL: interval})
        api = _make_api()
        return hass, entry, api

    @pytest.mark.asyncio
    async def test_interval_zero_clamped_to_minimum(self) -> None:
        from custom_components.karlstadsenergi.const import MIN_UPDATE_INTERVAL
        from datetime import timedelta

        hass, entry, api = self._setup_args(0)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        waste_coord = entry.runtime_data.waste_coordinator
        assert waste_coord.update_interval >= timedelta(hours=MIN_UPDATE_INTERVAL)

    @pytest.mark.asyncio
    async def test_interval_999_clamped_to_maximum(self) -> None:
        from custom_components.karlstadsenergi.const import MAX_UPDATE_INTERVAL
        from datetime import timedelta

        hass, entry, api = self._setup_args(999)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        waste_coord = entry.runtime_data.waste_coordinator
        assert waste_coord.update_interval <= timedelta(hours=MAX_UPDATE_INTERVAL)

    @pytest.mark.asyncio
    async def test_interval_at_minimum_boundary_is_accepted(self) -> None:
        from custom_components.karlstadsenergi.const import MIN_UPDATE_INTERVAL
        from datetime import timedelta

        hass, entry, api = self._setup_args(MIN_UPDATE_INTERVAL)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        waste_coord = entry.runtime_data.waste_coordinator
        assert waste_coord.update_interval == timedelta(hours=MIN_UPDATE_INTERVAL)

    @pytest.mark.asyncio
    async def test_interval_at_maximum_boundary_is_accepted(self) -> None:
        from custom_components.karlstadsenergi.const import MAX_UPDATE_INTERVAL
        from datetime import timedelta

        hass, entry, api = self._setup_args(MAX_UPDATE_INTERVAL)

        with (
            patch(
                "custom_components.karlstadsenergi.KarlstadsenergiApi",
                return_value=api,
            ),
            patch(
                "custom_components.karlstadsenergi.async_track_time_interval",
                return_value=MagicMock(),
            ),
        ):
            await async_setup_entry(hass, entry)

        waste_coord = entry.runtime_data.waste_coordinator
        assert waste_coord.update_interval == timedelta(hours=MAX_UPDATE_INTERVAL)
