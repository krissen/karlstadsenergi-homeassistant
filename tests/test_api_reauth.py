"""Tests for method-level re-auth with page revisits in api.py.

When session expires mid-flow, _request() (with retry_auth=False) raises
KarlstadsenergiAuthError. The calling methods (async_get_consumption,
async_get_flex_services, async_get_contract_details) must then:
  1. Re-authenticate
  2. Redo page visits (server-side state init)
  3. Retry the AJAX call

These tests verify that page visits happen AGAIN after re-auth.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.karlstadsenergi.api import (
    AUTH_PASSWORD,
    KarlstadsenergiApi,
    KarlstadsenergiAuthError,
)
from custom_components.karlstadsenergi.const import (
    URL_CONTRACT_DETAILS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page_visit_session() -> MagicMock:
    """Session mock whose .get() works as an async context manager.

    Each call to session.get(url) records the URL so we can assert
    which pages were visited and in what order.
    """
    mock_session = MagicMock()
    mock_session.closed = False

    def _make_cm(*args, **kwargs):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.get = MagicMock(side_effect=_make_cm)
    return mock_session


def _get_urls(mock_session: MagicMock) -> list[str]:
    """Extract the URLs passed to session.get() calls."""
    return [c.args[0] for c in mock_session.get.call_args_list if c.args]


# ---------------------------------------------------------------------------
# async_get_consumption -- happy path
# ---------------------------------------------------------------------------


class TestConsumptionHappyPath:
    async def test_returns_data_when_session_valid(self) -> None:
        """Session valid, page visits + AJAX succeed -> returns data."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}
        api._request = AsyncMock(return_value=expected)
        api._session = _make_page_visit_session()

        result = await api.async_get_consumption()

        assert result == expected
        # Page visits happened
        urls = _get_urls(api._session)
        assert any("start.aspx" in u for u in urls)
        assert any("consumption/consumption.aspx" in u for u in urls)


# ---------------------------------------------------------------------------
# async_get_consumption -- session expired, re-auth succeeds
# ---------------------------------------------------------------------------


class TestConsumptionReauthSuccess:
    async def test_redoes_page_visits_after_reauth(self) -> None:
        """First AJAX raises AuthError -> re-auth + redo visits + retry -> data."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}

        # _request: first call raises AuthError, second succeeds
        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        # authenticate_password succeeds on re-auth
        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        result = await api.async_get_consumption()

        assert result == expected

    async def test_page_visits_happen_twice(self) -> None:
        """After re-auth, start.aspx and consumption.aspx are visited again."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_consumption()

        urls = _get_urls(api._session)
        # Each page should be visited twice (once before first attempt, once after re-auth)
        start_visits = [
            u for u in urls if "start.aspx" in u and "consumption" not in u.lower()
        ]
        consumption_visits = [u for u in urls if "consumption/consumption.aspx" in u]
        assert len(start_visits) == 2, (
            f"Expected 2 start.aspx visits, got {len(start_visits)}: {urls}"
        )
        assert len(consumption_visits) == 2, (
            f"Expected 2 consumption.aspx visits, got {len(consumption_visits)}: {urls}"
        )

    async def test_authenticate_called_on_reauth(self) -> None:
        """Re-auth must actually call authenticate (or authenticate_password)."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_consumption()

        # authenticate_password should have been called for re-auth
        api.authenticate_password.assert_called()

    async def test_request_called_twice(self) -> None:
        """_request must be called twice: once failing, once succeeding."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_consumption()

        assert api._request.call_count == 2


# ---------------------------------------------------------------------------
# async_get_consumption -- re-auth fails
# ---------------------------------------------------------------------------


class TestConsumptionReauthFails:
    async def test_raises_auth_error_when_reauth_fails(self) -> None:
        """First AJAX raises AuthError -> re-auth fails -> AuthError propagates."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        api._request = AsyncMock(
            side_effect=KarlstadsenergiAuthError("Session expired")
        )

        # Re-auth also fails
        api.authenticate_password = AsyncMock(
            side_effect=KarlstadsenergiAuthError("Bad credentials")
        )
        api._session = _make_page_visit_session()

        with pytest.raises(KarlstadsenergiAuthError):
            await api.async_get_consumption()

    async def test_no_retry_when_reauth_fails(self) -> None:
        """When re-auth fails, _request should only have been called once."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        api._request = AsyncMock(
            side_effect=KarlstadsenergiAuthError("Session expired")
        )

        api.authenticate_password = AsyncMock(
            side_effect=KarlstadsenergiAuthError("Bad credentials")
        )
        api._session = _make_page_visit_session()

        with pytest.raises(KarlstadsenergiAuthError):
            await api.async_get_consumption()

        # Only one _request call (the failing one), no retry
        assert api._request.call_count == 1


# ---------------------------------------------------------------------------
# async_get_flex_services -- session expired, re-auth succeeds
# ---------------------------------------------------------------------------


class TestFlexServicesReauthSuccess:
    async def test_redoes_page_visit_after_reauth(self) -> None:
        """First AJAX raises AuthError -> re-auth + redo flex page visit + retry -> data."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ServiceId": 1, "Name": "Mat- och restavfall"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        result = await api.async_get_flex_services()

        assert result == expected

    async def test_flex_page_visited_twice(self) -> None:
        """After re-auth, flexservices.aspx must be visited again."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ServiceId": 1}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_flex_services()

        urls = _get_urls(api._session)
        flex_visits = [u for u in urls if "flexservices.aspx" in u.lower()]
        assert len(flex_visits) == 2, (
            f"Expected 2 flex page visits, got {len(flex_visits)}: {urls}"
        )

    async def test_authenticate_called_for_reauth(self) -> None:
        """Re-auth triggers authenticate_password."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ServiceId": 1}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_flex_services()

        api.authenticate_password.assert_called()

    async def test_request_called_twice(self) -> None:
        """_request called twice: first fails, second succeeds."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ServiceId": 1}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_flex_services()

        assert api._request.call_count == 2


# ---------------------------------------------------------------------------
# async_get_contract_details -- session expired, re-auth succeeds
# ---------------------------------------------------------------------------


class TestContractDetailsReauthSuccess:
    async def test_redoes_page_visit_after_reauth(self) -> None:
        """First AJAX raises AuthError -> re-auth + redo contracts page + retry -> data."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc", "UtilityName": "Elnät"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        result = await api.async_get_contract_details(["site-1"])

        assert result == expected

    async def test_contracts_page_visited_twice(self) -> None:
        """After re-auth, contracts.aspx must be visited again."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_contract_details(["site-1"])

        urls = _get_urls(api._session)
        contract_visits = [u for u in urls if "contracts.aspx" in u.lower()]
        assert len(contract_visits) == 2, (
            f"Expected 2 contract page visits, got {len(contract_visits)}: {urls}"
        )

    async def test_authenticate_called_for_reauth(self) -> None:
        """Re-auth triggers authenticate_password."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_contract_details(["site-1"])

        api.authenticate_password.assert_called()

    async def test_request_called_twice(self) -> None:
        """_request called twice: first fails, second succeeds."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_contract_details(["site-1"])

        assert api._request.call_count == 2

    async def test_passes_site_ids_on_retry(self) -> None:
        """The retry call must pass the same usePlaces argument."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc"}]

        api._request = AsyncMock(
            side_effect=[KarlstadsenergiAuthError("Session expired"), expected]
        )

        async def _do_auth():
            api._authenticated = True
            return True

        api.authenticate_password = AsyncMock(side_effect=_do_auth)
        api._session = _make_page_visit_session()

        await api.async_get_contract_details(["site-1", "site-2"])

        # The second call (retry) should have the same arguments
        retry_call = api._request.call_args_list[1]
        assert retry_call.args[0] == URL_CONTRACT_DETAILS
        assert retry_call.args[1] == {"usePlaces": ["site-1", "site-2"]}


# ---------------------------------------------------------------------------
# async_get_consumption -- _request receives retry_auth=False
# ---------------------------------------------------------------------------


class TestConsumptionRetryAuthFlag:
    async def test_request_called_with_retry_auth_false(self) -> None:
        """The method must pass retry_auth=False to _request()."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={"data": "ok"})
        api._session = _make_page_visit_session()

        await api.async_get_consumption()

        # Check that retry_auth=False was passed
        call_kwargs = api._request.call_args
        # It could be a positional or keyword arg
        if len(call_kwargs.args) > 1:
            # Positional: _request(url, json_data, retry_auth)
            # or keyword
            pass
        assert call_kwargs.kwargs.get("retry_auth") is False or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] is False
        ), f"Expected retry_auth=False, got call: {call_kwargs}"


class TestFlexServicesRetryAuthFlag:
    async def test_request_called_with_retry_auth_false(self) -> None:
        """async_get_flex_services must pass retry_auth=False to _request()."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[])
        api._session = _make_page_visit_session()

        await api.async_get_flex_services()

        call_kwargs = api._request.call_args
        assert call_kwargs.kwargs.get("retry_auth") is False or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] is False
        ), f"Expected retry_auth=False, got call: {call_kwargs}"


class TestContractDetailsRetryAuthFlag:
    async def test_request_called_with_retry_auth_false(self) -> None:
        """async_get_contract_details must pass retry_auth=False to _request()."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[])
        api._session = _make_page_visit_session()

        await api.async_get_contract_details(["site-1"])

        call_kwargs = api._request.call_args
        assert call_kwargs.kwargs.get("retry_auth") is False or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] is False
        ), f"Expected retry_auth=False, got call: {call_kwargs}"
