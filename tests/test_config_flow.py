"""Tests for config flow critical paths.

These tests exercise the flow logic in isolation using minimal mocking.
No live HA instance or pytest-homeassistant-custom-component required.

The config flow is tested at the unit level by instantiating the flow class
directly and driving it through its async_step_* methods.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi.api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    KarlstadsenergiConnectionError,
)
from custom_components.karlstadsenergi.config_flow import (
    _QR_STORE,
    KarlstadsenergiBankIDQRView,
    KarlstadsenergiConfigFlow,
)
from custom_components.karlstadsenergi.const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flow(source: str = "user") -> KarlstadsenergiConfigFlow:
    """Create a config flow instance with a minimal mock hass."""
    flow = KarlstadsenergiConfigFlow()
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry.return_value = None
    flow.hass = hass
    # Provide a context dict (needed by _abort_if_unique_id_configured etc.)
    flow.context = {"source": source}
    return flow


def _mock_password_api(
    *,
    auth_side_effect: Exception | None = None,
    cookies: dict | None = None,
) -> MagicMock:
    """Create a mock API for the password flow."""
    mock_api = MagicMock()
    if auth_side_effect:
        mock_api.authenticate_password = AsyncMock(side_effect=auth_side_effect)
    else:
        mock_api.authenticate_password = AsyncMock()
    mock_api.async_get_next_flex_dates = AsyncMock(return_value=[])
    mock_api.get_session_cookies = MagicMock(return_value=cookies or {"session": "abc"})
    mock_api.async_close = AsyncMock()
    return mock_api


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
        assert not result.get("errors")

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
    async def test_default_auth_method_is_password(self) -> None:
        """With no input, the form default should be AUTH_PASSWORD."""
        flow = _make_flow()
        result = await flow.async_step_user(user_input=None)
        for key in result["data_schema"].schema:
            if str(key) == CONF_AUTH_METHOD:
                assert key.default() == AUTH_PASSWORD
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
        """A valid personnummer routes to the bankid step (no unique_id check)."""
        flow = _make_flow()

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
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        mock_api = _mock_password_api(
            auth_side_effect=KarlstadsenergiAuthError("bad credentials")
        )
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
    async def test_locked_account_shows_account_locked(self) -> None:
        """A locked account must show account_locked, not invalid_auth."""
        from custom_components.karlstadsenergi.api import (
            KarlstadsenergiAccountLockedError,
        )

        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        mock_api = _mock_password_api(
            auth_side_effect=KarlstadsenergiAccountLockedError("locked")
        )
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_password(
                user_input={"customer_number": "166667", "password": "pw"}
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "account_locked"

    @pytest.mark.asyncio
    async def test_connection_error_shows_cannot_connect(self) -> None:
        from custom_components.karlstadsenergi.api import KarlstadsenergiConnectionError

        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        mock_api = _mock_password_api(
            auth_side_effect=KarlstadsenergiConnectionError("timeout")
        )
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
        """Successful password auth should return a 'create_entry' result."""
        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        mock_api = _mock_password_api()
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
        assert result["data"]["customer_code"] == "123456"

    @pytest.mark.asyncio
    async def test_duplicate_customer_aborts(self) -> None:
        """Password flow with already-configured customer_number should abort."""
        from homeassistant.data_entry_flow import AbortFlow

        flow = _make_flow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=AbortFlow("already_configured")
        )

        with pytest.raises(AbortFlow, match="already_configured"):
            await flow.async_step_password(
                user_input={"customer_number": "123456", "password": "pw"}
            )
        flow.async_set_unique_id.assert_called_once_with("123456")

    @pytest.mark.asyncio
    async def test_reauth_updates_and_schedules_reload(self) -> None:
        """Reauth completion must update the entry and explicitly schedule a
        reload. The update listener only reloads on options changes, and an
        entry that failed setup has no listener registered, so reauth cannot
        rely on the listener to reload."""
        flow = _make_flow(source="reauth")
        flow.async_set_unique_id = AsyncMock()
        reauth_entry = MagicMock()
        reauth_entry.entry_id = "reauth-entry-id"
        flow._get_reauth_entry = MagicMock(return_value=reauth_entry)

        mock_api = _mock_password_api()
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_password(
                user_input={"customer_number": "123456", "password": "correct"}
            )

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(
            "reauth-entry-id"
        )


# ---------------------------------------------------------------------------
# Options flow: update interval validation
# ---------------------------------------------------------------------------


class TestOptionsFlow:
    def _make_options_flow(self) -> Any:
        from custom_components.karlstadsenergi.config_flow import (
            KarlstadsenergiOptionsFlow,
        )

        flow = KarlstadsenergiOptionsFlow()
        flow.hass = MagicMock()
        # Mock config_entry property
        entry = MagicMock()
        entry.options = {}
        flow._config_entry = entry
        # OptionsFlow uses self.config_entry which is a property;
        # patch it on the instance
        type(flow).config_entry = property(lambda self: self._config_entry)
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

    @pytest.mark.asyncio
    async def test_valid_history_years_creates_entry(self) -> None:
        from custom_components.karlstadsenergi.const import (
            CONF_HISTORY_YEARS,
            CONF_UPDATE_INTERVAL,
        )

        flow = self._make_options_flow()
        result = await flow.async_step_init(
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_HISTORY_YEARS: 5}
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_HISTORY_YEARS] == 5

    @pytest.mark.asyncio
    async def test_history_years_too_low_shows_error(self) -> None:
        from custom_components.karlstadsenergi.const import (
            CONF_HISTORY_YEARS,
            CONF_UPDATE_INTERVAL,
        )

        flow = self._make_options_flow()
        result = await flow.async_step_init(
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_HISTORY_YEARS: 0}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_history_years"

    @pytest.mark.asyncio
    async def test_history_years_too_high_shows_error(self) -> None:
        from custom_components.karlstadsenergi.const import (
            CONF_HISTORY_YEARS,
            CONF_UPDATE_INTERVAL,
        )

        flow = self._make_options_flow()
        result = await flow.async_step_init(
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_HISTORY_YEARS: 11}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_history_years"

    @pytest.mark.asyncio
    async def test_values_coerced_to_int(self) -> None:
        from custom_components.karlstadsenergi.const import (
            CONF_HISTORY_YEARS,
            CONF_UPDATE_INTERVAL,
        )

        flow = self._make_options_flow()
        result = await flow.async_step_init(
            user_input={CONF_UPDATE_INTERVAL: "6", CONF_HISTORY_YEARS: "3"}
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_UPDATE_INTERVAL] == 6
        assert result["data"][CONF_HISTORY_YEARS] == 3
        assert isinstance(result["data"][CONF_UPDATE_INTERVAL], int)
        assert isinstance(result["data"][CONF_HISTORY_YEARS], int)


# ---------------------------------------------------------------------------
# B7: Reauth flow
# ---------------------------------------------------------------------------


class TestStepReauth:
    @pytest.mark.asyncio
    async def test_stores_personnummer_from_entry_data(self) -> None:
        """async_step_reauth must store the personnummer from the existing entry."""
        flow = _make_flow(source="reauth")

        entry_data = {
            CONF_PERSONNUMMER: "199001011234",
            CONF_AUTH_METHOD: AUTH_PASSWORD,
        }
        # async_step_reauth immediately calls async_step_reauth_confirm (no input),
        # which returns a form -- we only care about the side-effect on flow state.
        await flow.async_step_reauth(entry_data)

        assert flow._personnummer == "199001011234"

    @pytest.mark.asyncio
    async def test_stores_auth_method_from_entry_data(self) -> None:
        flow = _make_flow(source="reauth")

        entry_data = {
            CONF_PERSONNUMMER: "199001011234",
            CONF_AUTH_METHOD: AUTH_BANKID,
        }
        await flow.async_step_reauth(entry_data)

        assert flow._auth_method == AUTH_BANKID

    @pytest.mark.asyncio
    async def test_routes_to_reauth_confirm(self) -> None:
        """async_step_reauth must advance to the reauth_confirm step."""
        flow = _make_flow(source="reauth")

        entry_data = {
            CONF_PERSONNUMMER: "199001011234",
            CONF_AUTH_METHOD: AUTH_PASSWORD,
        }
        result = await flow.async_step_reauth(entry_data)

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm_password"

    @pytest.mark.asyncio
    async def test_defaults_auth_method_to_password_when_missing(self) -> None:
        """Absent CONF_AUTH_METHOD in entry_data must default to AUTH_PASSWORD."""
        flow = _make_flow(source="reauth")

        await flow.async_step_reauth({CONF_PERSONNUMMER: "199001011234"})

        assert flow._auth_method == AUTH_PASSWORD


class TestStepReauthConfirm:
    @pytest.mark.asyncio
    async def test_no_input_returns_reauth_confirm_form(self) -> None:
        """With no user_input the form must be shown."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_PASSWORD

        result = await flow.async_step_reauth_confirm(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm_password"

    @pytest.mark.asyncio
    async def test_bankid_returns_reauth_confirm_bankid_form(self) -> None:
        """BankID reauth must show the bankid-specific form."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_BANKID

        result = await flow.async_step_reauth_confirm(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm_bankid"

    @pytest.mark.asyncio
    async def test_form_does_not_expose_personnummer(self) -> None:
        """The reauth_confirm form must NOT expose personnummer (security H10)."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_PASSWORD

        result = await flow.async_step_reauth_confirm(user_input=None)

        placeholders = result.get("description_placeholders") or {}
        assert "personnummer" not in placeholders

    @pytest.mark.asyncio
    async def test_with_input_routes_to_password_step_for_password_auth(self) -> None:
        """Submitting the confirm form when auth_method=password must go to password."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_PASSWORD

        result = await flow.async_step_reauth_confirm(user_input={})

        assert result["type"] == "form"
        assert result["step_id"] == "password"

    @pytest.mark.asyncio
    async def test_with_input_routes_to_bankid_step_for_bankid_auth(self) -> None:
        """Submitting the confirm form when auth_method=bankid must go to bankid."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_BANKID

        mock_api = MagicMock()
        mock_api.bankid_initiate = AsyncMock(
            return_value={
                "order_ref": "ref-reauth",
                "auto_start_token": "tok",
                "qr_code_base64": "",
                "transaction_id": "txn-reauth",
            }
        )

        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_reauth_confirm(user_input={})

        assert result["type"] == "form"
        assert result["step_id"] == "bankid"

    @pytest.mark.asyncio
    async def test_empty_schema_on_confirm_form(self) -> None:
        """The reauth_confirm form has no fields -- schema must be empty."""
        flow = _make_flow(source="reauth")
        flow._personnummer = "199001011234"
        flow._auth_method = AUTH_PASSWORD

        result = await flow.async_step_reauth_confirm(user_input=None)

        schema_keys = list(result["data_schema"].schema.keys())
        assert schema_keys == []


# ---------------------------------------------------------------------------
# Step: bankid (QR display + resilient re-initiation)
# ---------------------------------------------------------------------------


def _make_bankid_api(qr_b64: str = "") -> MagicMock:
    """Mock API that initiates a BankID order."""
    mock_api = MagicMock()
    mock_api.bankid_initiate = AsyncMock(
        return_value={
            "order_ref": "ref123",
            "auto_start_token": "token",
            "qr_start_token": "qrt",
            "qr_code_base64": qr_b64,
            "transaction_id": "txn123",
            "data_field": "",
        }
    )
    mock_api.bankid_poll = AsyncMock()
    mock_api.async_close = AsyncMock()
    return mock_api


class TestStepBankid:
    """The BankID step must show a valid order and never poll a dead API."""

    @pytest.mark.asyncio
    async def test_submit_with_no_live_api_reinitiates_without_crash(self) -> None:
        """Regression: a Submit after the API was cleaned up must not crash.

        Previously this raised AttributeError ('NoneType' has no bankid_poll)
        because the Submit branch polled self._api while it was None.
        """
        flow = _make_flow()
        flow._personnummer = "199001011234"
        flow._api = None  # simulate cleanup after a prior failed attempt
        flow._bankid_init = {}

        mock_api = _make_bankid_api()
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            # user_input is a Submit (dict), but there is no live order yet
            result = await flow.async_step_bankid(user_input={})

        assert result["type"] == "form"
        assert result["step_id"] == "bankid"
        # A fresh order was created and the stale Submit was NOT polled.
        mock_api.bankid_initiate.assert_awaited()
        mock_api.bankid_poll.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pending_reinitiates_fresh_order(self) -> None:
        """A pending (unsigned) order must yield a new order, keeping the API."""
        flow = _make_flow()
        flow._personnummer = "199001011234"

        mock_api = _make_bankid_api()
        # Poll always reports "outstanding" (status 2) -> pending.
        mock_api.bankid_poll = AsyncMock(return_value={"status": 2, "data": {}})

        with (
            patch(
                "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
                return_value=mock_api,
            ),
            patch(
                "custom_components.karlstadsenergi.config_flow.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            # First entry creates the order, then a Submit polls it.
            await flow.async_step_bankid(user_input=None)
            result = await flow.async_step_bankid(user_input={})

        assert result["step_id"] == "bankid"
        assert result["errors"] == {"base": "bankid_pending"}
        # API stays alive for the next attempt; a fresh order was created.
        assert flow._api is mock_api
        assert mock_api.bankid_initiate.await_count >= 2

    @pytest.mark.asyncio
    async def test_connection_error_on_initiate_returns_to_user_form(self) -> None:
        """A connection error while initiating bails to the user step."""
        flow = _make_flow()
        flow._personnummer = "199001011234"
        flow._api = None
        flow._bankid_init = {}

        mock_api = _make_bankid_api()
        mock_api.bankid_initiate = AsyncMock(
            side_effect=KarlstadsenergiConnectionError("boom")
        )
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_bankid(user_input=None)

        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_qr_png_is_cached_and_linked(self) -> None:
        """Initiating an order caches the decoded QR PNG and links to it."""
        png = base64.b64encode(b"PNGDATA").decode("ascii")
        flow = _make_flow()
        flow._personnummer = "199001011234"

        mock_api = _make_bankid_api(qr_b64=png)
        with patch(
            "custom_components.karlstadsenergi.config_flow.KarlstadsenergiApi",
            return_value=mock_api,
        ):
            result = await flow.async_step_bankid(user_input=None)

        assert _QR_STORE["txn123"] == b"PNGDATA"
        assert result["description_placeholders"]["qr_url"].endswith("/txn123")


class TestBankIDQRView:
    """The HTTP view that serves the QR PNG cross-device."""

    @pytest.mark.asyncio
    async def test_known_token_returns_png(self) -> None:
        _QR_STORE["tok-known"] = b"imgbytes"
        view = KarlstadsenergiBankIDQRView()
        resp = await view.get(MagicMock(), "tok-known")
        assert resp.status == 200
        assert resp.body == b"imgbytes"
        assert resp.content_type == "image/png"
        _QR_STORE.pop("tok-known", None)

    @pytest.mark.asyncio
    async def test_unknown_token_returns_404(self) -> None:
        view = KarlstadsenergiBankIDQRView()
        resp = await view.get(MagicMock(), "tok-missing")
        assert resp.status == 404
