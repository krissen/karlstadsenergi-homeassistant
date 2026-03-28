"""Tests for config flow critical paths.

These tests exercise the flow logic in isolation using minimal mocking.
No live HA instance or pytest-homeassistant-custom-component required.

The config flow is tested at the unit level by instantiating the flow class
directly and driving it through its async_step_* methods.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi.api import AUTH_BANKID, AUTH_PASSWORD
from custom_components.karlstadsenergi.config_flow import KarlstadsenergiConfigFlow
from custom_components.karlstadsenergi.const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flow() -> KarlstadsenergiConfigFlow:
    """Create a config flow instance with a minimal mock hass."""
    flow = KarlstadsenergiConfigFlow()
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry.return_value = None
    flow.hass = hass
    # Provide a context dict (needed by _abort_if_unique_id_configured etc.)
    flow.context = {"source": "user"}
    return flow


# ---------------------------------------------------------------------------
# Step: user (auth method selection)
# ---------------------------------------------------------------------------


class TestStepUser:
    @pytest.mark.asyncio
    async def test_no_input_returns_form(self) -> None:
        """async_step_user with no input must show the user form."""
        flow = _make_flow()
        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_no_input_form_has_auth_method_field(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_user(user_input=None)

        schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
        assert CONF_AUTH_METHOD in schema_keys

    @pytest.mark.asyncio
    async def test_no_input_errors_are_empty(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_user(user_input=None)
        assert result.get("errors", {}) == {}

    @pytest.mark.asyncio
    async def test_password_method_routes_to_password_step(self) -> None:
        """Selecting AUTH_PASSWORD must advance to step 'password'."""
        flow = _make_flow()
        result = await flow.async_step_user(
            user_input={CONF_AUTH_METHOD: AUTH_PASSWORD}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "password"

    @pytest.mark.asyncio
    async def test_bankid_method_routes_to_bankid_personnummer_step(self) -> None:
        """Selecting AUTH_BANKID must advance to step 'bankid_personnummer'."""
        flow = _make_flow()
        result = await flow.async_step_user(user_input={CONF_AUTH_METHOD: AUTH_BANKID})
        assert result["type"] == "form"
        assert result["step_id"] == "bankid_personnummer"

    @pytest.mark.asyncio
    async def test_default_auth_method_is_bankid(self) -> None:
        """With no input, the form default should be AUTH_BANKID."""
        flow = _make_flow()
        result = await flow.async_step_user(user_input=None)
        # Inspect the schema default for CONF_AUTH_METHOD
        for key in result["data_schema"].schema:
            if str(key) == CONF_AUTH_METHOD:
                assert key.default() == AUTH_BANKID
                break
        else:
            pytest.fail(f"{CONF_AUTH_METHOD} not found in form schema")


# ---------------------------------------------------------------------------
# Step: bankid_personnummer
# ---------------------------------------------------------------------------


class TestStepBankidPersonnummer:
    @pytest.mark.asyncio
    async def test_no_input_returns_form(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_bankid_personnummer(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "bankid_personnummer"

    @pytest.mark.asyncio
    async def test_form_has_personnummer_field(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_bankid_personnummer(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
        assert CONF_PERSONNUMMER in schema_keys

    @pytest.mark.asyncio
    async def test_empty_personnummer_shows_error(self) -> None:
        """Empty personnummer should stay on the form with an error."""
        flow = _make_flow()
        result = await flow.async_step_bankid_personnummer(
            user_input={CONF_PERSONNUMMER: ""}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "bankid_personnummer"
        assert "base" in result.get("errors", {})

    @pytest.mark.asyncio
    async def test_valid_personnummer_advances_to_bankid(self) -> None:
        """A valid personnummer routes to the bankid step."""
        flow = _make_flow()

        # Stub out unique_id methods and bankid_initiate so we don't hit network
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref123",
                "auto_start_token": "token",
                "qr_code_base64": "",
                "transaction_id": "txn123",
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


# ---------------------------------------------------------------------------
# Step: password (form display only -- no network)
# ---------------------------------------------------------------------------


class TestStepPassword:
    @pytest.mark.asyncio
    async def test_no_input_returns_form(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_password(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "password"

    @pytest.mark.asyncio
    async def test_form_has_required_fields(self) -> None:
        flow = _make_flow()
        result = await flow.async_step_password(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
        assert "customer_number" in schema_keys
        assert "password" in schema_keys

    @pytest.mark.asyncio
    async def test_auth_error_shows_invalid_auth(self) -> None:
        """When the API raises KarlstadsenergiAuthError, show invalid_auth."""
        from custom_components.karlstadsenergi.api import KarlstadsenergiAuthError

        flow = _make_flow()
        mock_api = MagicMock()
        mock_api.authenticate_password = AsyncMock(
            side_effect=KarlstadsenergiAuthError("bad credentials")
        )
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_password(
                user_input={"customer_number": "123456", "password": "wrong"}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "password"
        assert result["errors"]["base"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_connection_error_shows_cannot_connect(self) -> None:
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        flow = _make_flow()
        mock_api = MagicMock()
        mock_api.authenticate_password = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("timeout")
        )
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_password(
                user_input={"customer_number": "123456", "password": "pw"}
            )

        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_successful_auth_creates_entry(self) -> None:
        """Successful password auth should return an 'create_entry' result."""
        flow = _make_flow()
        mock_api = MagicMock()
        mock_api.authenticate_password = AsyncMock()
        mock_api.async_get_next_flex_dates = AsyncMock(return_value=[])
        mock_api.get_session_cookies = MagicMock(return_value={"session": "abc"})
        mock_api.async_close = AsyncMock()

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_password(
                user_input={"customer_number": "123456", "password": "correct"}
            )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_PERSONNUMMER] == "123456"
        assert result["data"][CONF_AUTH_METHOD] == AUTH_PASSWORD


# ---------------------------------------------------------------------------
# Options flow: update interval validation
# ---------------------------------------------------------------------------


class TestOptionsFlow:
    def _make_options_flow(self) -> Any:
        from custom_components.karlstadsenergi.config_flow import (
            KarlstadsenergiOptionsFlow,
        )

        entry = MagicMock()
        entry.options = {}
        flow = KarlstadsenergiOptionsFlow(entry)
        flow.hass = MagicMock()
        return flow

    @pytest.mark.asyncio
    async def test_no_input_returns_form(self) -> None:
        flow = self._make_options_flow()
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_valid_interval_creates_entry(self) -> None:
        from custom_components.karlstadsenergi.const import CONF_UPDATE_INTERVAL

        flow = self._make_options_flow()
        result = await flow.async_step_init(user_input={CONF_UPDATE_INTERVAL: 12})
        assert result["type"] == "create_entry"
        assert result["data"][CONF_UPDATE_INTERVAL] == 12
