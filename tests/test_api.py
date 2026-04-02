"""Tests for api.py -- _parse_aspnet_response and KarlstadsenergiApi."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.karlstadsenergi.api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    KarlstadsenergiApi,
    KarlstadsenergiApiError,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
    _parse_aspnet_response,
)


# ---------------------------------------------------------------------------
# _parse_aspnet_response
# ---------------------------------------------------------------------------


class TestParseAspnetResponse:
    def test_json_string_is_double_parsed(self) -> None:
        assert _parse_aspnet_response({"d": '{"key": "value"}'}) == {"key": "value"}

    def test_list_value_returned_as_is(self) -> None:
        assert _parse_aspnet_response({"d": [1, 2, 3]}) == [1, 2, 3]

    def test_plain_string_returned_verbatim(self) -> None:
        assert _parse_aspnet_response({"d": "plain text"}) == "plain text"

    def test_none_value_returns_none(self) -> None:
        assert _parse_aspnet_response({"d": None}) is None

    def test_missing_d_key_returns_none(self) -> None:
        assert _parse_aspnet_response({}) is None

    def test_invalid_json_string_returned_verbatim(self) -> None:
        assert _parse_aspnet_response({"d": "not json {"}) == "not json {"

    def test_boolean_true_returned_as_is(self) -> None:
        assert _parse_aspnet_response({"d": True}) is True

    def test_boolean_false_returned_as_is(self) -> None:
        assert _parse_aspnet_response({"d": False}) is False

    def test_integer_value_returned_as_is(self) -> None:
        assert _parse_aspnet_response({"d": 42}) == 42

    def test_nested_json_string_is_fully_parsed(self) -> None:
        result = _parse_aspnet_response({"d": '{"items": [1, 2], "count": 2}'})
        assert result == {"items": [1, 2], "count": 2}

    def test_empty_dict_d_value_returned_as_is(self) -> None:
        assert _parse_aspnet_response({"d": {}}) == {}

    def test_extra_keys_are_ignored(self) -> None:
        # Only "d" is consumed; other keys are ignored
        result = _parse_aspnet_response({"d": "hello", "other": "ignored"})
        assert result == "hello"

    def test_json_array_string_is_double_parsed(self) -> None:
        result = _parse_aspnet_response({"d": "[1, 2, 3]"})
        assert result == [1, 2, 3]

    def test_empty_string_returned_as_is(self) -> None:
        # Empty string is not valid JSON, so returned as-is
        result = _parse_aspnet_response({"d": ""})
        assert result == ""


# ---------------------------------------------------------------------------
# KarlstadsenergiApi constructor
# ---------------------------------------------------------------------------


class TestApiConstructor:
    def test_stores_personnummer(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "testpass")
        assert api._personnummer == "1234567890"

    def test_stores_auth_method(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "testpass")
        assert api._auth_method == AUTH_PASSWORD

    def test_stores_password(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "secret")
        assert api._password == "secret"

    def test_defaults_to_bankid_auth(self) -> None:
        api = KarlstadsenergiApi("1234567890")
        assert api._auth_method == AUTH_BANKID

    def test_session_initially_none(self) -> None:
        api = KarlstadsenergiApi("1234567890")
        assert api._session is None

    def test_not_authenticated_initially(self) -> None:
        api = KarlstadsenergiApi("1234567890")
        assert api._authenticated is False

    def test_saved_cookies_initially_none(self) -> None:
        api = KarlstadsenergiApi("1234567890")
        assert api._saved_cookies is None


# ---------------------------------------------------------------------------
# set_session_cookies / get_session_cookies
# ---------------------------------------------------------------------------


class TestSessionCookies:
    def test_set_session_cookies_stores_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        cookies = {"ASP.NET_SessionId": "abc123", ".PORTALAUTH": "xyz"}
        api.set_session_cookies(cookies)
        assert api._saved_cookies == cookies

    def test_get_session_cookies_returns_empty_when_no_session(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        assert api.get_session_cookies() == {}

    def test_get_session_cookies_returns_empty_when_session_closed(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = True
        api._session = mock_session
        assert api.get_session_cookies() == {}


# ---------------------------------------------------------------------------
# _ensure_session
# ---------------------------------------------------------------------------


class TestEnsureSession:
    @pytest.mark.asyncio
    async def test_creates_new_session_when_none(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        with patch(
            "custom_components.karlstadsenergi.api.aiohttp.ClientSession"
        ) as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_jar = MagicMock()
            mock_session.cookie_jar = mock_jar
            mock_cls.return_value = mock_session
            with patch(
                "custom_components.karlstadsenergi.api.aiohttp.CookieJar"
            ) as mock_jar_cls:
                mock_jar_cls.return_value = mock_jar
                session = await api._ensure_session()
        assert session is mock_session
        assert api._session is mock_session

    @pytest.mark.asyncio
    async def test_reuses_existing_open_session(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = False
        api._session = mock_session
        session = await api._ensure_session()
        assert session is mock_session

    @pytest.mark.asyncio
    async def test_creates_new_session_when_closed(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        closed_session = MagicMock()
        closed_session.closed = True
        api._session = closed_session

        with patch(
            "custom_components.karlstadsenergi.api.aiohttp.ClientSession"
        ) as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_jar = MagicMock()
            mock_session.cookie_jar = mock_jar
            mock_cls.return_value = mock_session
            with patch(
                "custom_components.karlstadsenergi.api.aiohttp.CookieJar"
            ) as mock_jar_cls:
                mock_jar_cls.return_value = mock_jar
                session = await api._ensure_session()

        assert session is mock_session

    @pytest.mark.asyncio
    async def test_restores_saved_cookies_on_new_session(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api.set_session_cookies({"ASP.NET_SessionId": "abc"})

        with patch(
            "custom_components.karlstadsenergi.api.aiohttp.ClientSession"
        ) as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_jar = MagicMock()
            mock_session.cookie_jar = mock_jar
            mock_cls.return_value = mock_session
            with patch(
                "custom_components.karlstadsenergi.api.aiohttp.CookieJar"
            ) as mock_jar_cls:
                mock_jar_cls.return_value = mock_jar
                await api._ensure_session()

        # Cookie jar update_cookies should be called once per saved cookie
        mock_jar.update_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_authenticated_true_when_cookies_restored(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api.set_session_cookies({"ASP.NET_SessionId": "abc"})

        with patch(
            "custom_components.karlstadsenergi.api.aiohttp.ClientSession"
        ) as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_jar = MagicMock()
            mock_session.cookie_jar = mock_jar
            mock_cls.return_value = mock_session
            with patch(
                "custom_components.karlstadsenergi.api.aiohttp.CookieJar"
            ) as mock_jar_cls:
                mock_jar_cls.return_value = mock_jar
                await api._ensure_session()

        assert api._authenticated is True

    @pytest.mark.asyncio
    async def test_does_not_set_authenticated_without_cookies(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")

        with patch(
            "custom_components.karlstadsenergi.api.aiohttp.ClientSession"
        ) as mock_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_jar = MagicMock()
            mock_session.cookie_jar = mock_jar
            mock_cls.return_value = mock_session
            with patch(
                "custom_components.karlstadsenergi.api.aiohttp.CookieJar"
            ) as mock_jar_cls:
                mock_jar_cls.return_value = mock_jar
                await api._ensure_session()

        assert api._authenticated is False


# ---------------------------------------------------------------------------
# authenticate() routing
# ---------------------------------------------------------------------------


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_routes_to_password_for_password_method(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "testpass")
        api.authenticate_password = AsyncMock(return_value=True)
        await api.authenticate()
        api.authenticate_password.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_to_bankid_for_bankid_method(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        with pytest.raises(
            KarlstadsenergiAuthError, match="BankID requires interactive"
        ):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_returns_true_if_already_authenticated(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api.authenticate_password = AsyncMock(return_value=True)
        result = await api.authenticate()
        assert result is True
        api.authenticate_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_propagates_auth_error_from_password(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "wrong")
        api.authenticate_password = AsyncMock(
            side_effect=KarlstadsenergiAuthError("bad credentials")
        )
        with pytest.raises(KarlstadsenergiAuthError):
            await api.authenticate()


# ---------------------------------------------------------------------------
# async_close
# ---------------------------------------------------------------------------


class TestAsyncClose:
    @pytest.mark.asyncio
    async def test_closes_open_session(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        api._session = mock_session
        api._authenticated = True

        await api.async_close()

        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_authenticated_false_after_close(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        api._session = mock_session
        api._authenticated = True

        await api.async_close()

        assert api._authenticated is False

    @pytest.mark.asyncio
    async def test_sets_session_to_none_after_close(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        api._session = mock_session

        await api.async_close()

        assert api._session is None

    @pytest.mark.asyncio
    async def test_no_error_when_no_session(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        # Should not raise
        await api.async_close()

    @pytest.mark.asyncio
    async def test_no_error_when_session_already_closed(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.closed = True
        mock_session.close = AsyncMock()
        api._session = mock_session

        await api.async_close()
        mock_session.close.assert_not_called()


# ---------------------------------------------------------------------------
# async_heartbeat
# ---------------------------------------------------------------------------


def _make_cm_session_get(mock_resp: MagicMock) -> MagicMock:
    """Return a session mock whose .get() works as an async context manager.

    aiohttp uses ``async with session.get(...) as resp``, so session.get must
    return an object that supports __aenter__ / __aexit__.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=cm)
    mock_session.closed = False
    return mock_session


class TestAsyncHeartbeat:
    @pytest.mark.asyncio
    async def test_returns_true_on_200(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_resp = MagicMock()
        mock_resp.status = 200

        api._session = _make_cm_session_get(mock_resp)

        result = await api.async_heartbeat()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)
        mock_session.closed = False
        api._session = mock_session

        result = await api.async_heartbeat()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_non_200(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_resp = MagicMock()
        mock_resp.status = 503

        api._session = _make_cm_session_get(mock_resp)

        result = await api.async_heartbeat()
        assert result is False


# ---------------------------------------------------------------------------
# async_get_next_flex_dates -- response parsing
# ---------------------------------------------------------------------------


class TestAsyncGetNextFlexDates:
    @pytest.mark.asyncio
    async def test_returns_list_when_result_is_list(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        expected = [{"Date": "2026-04-15", "Type": "Mat- och restavfall"}]
        api._request = AsyncMock(return_value=expected)

        result = await api.async_get_next_flex_dates()
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_is_not_list(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._request = AsyncMock(return_value={"unexpected": "dict"})

        result = await api.async_get_next_flex_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_none_result(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._request = AsyncMock(return_value=None)

        result = await api.async_get_next_flex_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_json_string_result(self) -> None:
        """If _request returns a JSON string, it should be re-parsed."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        import json

        raw_list = [{"Date": "2026-04-15", "Type": "Mat- och restavfall"}]
        api._request = AsyncMock(return_value=json.dumps(raw_list))

        result = await api.async_get_next_flex_dates()
        assert result == raw_list


# ---------------------------------------------------------------------------
# async_get_flex_dates -- response parsing
# ---------------------------------------------------------------------------


class TestAsyncGetFlexDates:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_service_ids(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._request = AsyncMock()

        result = await api.async_get_flex_dates([])
        assert result == {}
        api._request.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_dict_when_result_is_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        expected = {"123": "2026-04-15"}
        api._request = AsyncMock(return_value=expected)

        result = await api.async_get_flex_dates([123])
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_when_result_is_not_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._request = AsyncMock(return_value=[1, 2, 3])

        result = await api.async_get_flex_dates([123])
        assert result == {}

    @pytest.mark.asyncio
    async def test_joins_multiple_service_ids_with_pipe(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._request = AsyncMock(return_value={})

        await api.async_get_flex_dates([1, 2, 3])
        # _request is called with (url, {"flexServiceIds": "1|2|3"})
        args, _ = api._request.call_args
        assert args[1]["flexServiceIds"] == "1|2|3"


# ---------------------------------------------------------------------------
# _request -- auth retry behavior
# ---------------------------------------------------------------------------


class TestRequest:
    @pytest.mark.asyncio
    async def test_triggers_auth_when_not_authenticated(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = False
        api.authenticate = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json = AsyncMock(return_value={"d": [1, 2, 3]})
        mock_resp.release = AsyncMock()

        api._post = AsyncMock(return_value=mock_resp)

        await api._request("http://example.com/api")
        api.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_auth_on_302(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        redirect_resp = MagicMock()
        redirect_resp.status = 302
        redirect_resp.release = AsyncMock()

        ok_resp = MagicMock()
        ok_resp.status = 200
        ok_resp.headers = {"Content-Type": "application/json"}
        ok_resp.json = AsyncMock(return_value={"d": "ok"})
        ok_resp.release = AsyncMock()

        api._post = AsyncMock(side_effect=[redirect_resp, ok_resp])

        async def _set_auth():
            api._authenticated = True

        api.authenticate = AsyncMock(side_effect=_set_auth)

        result = await api._request("http://example.com/api")
        # Called once for re-auth after 302 (recursive call sees _authenticated=True)
        assert api.authenticate.call_count == 1
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_raises_auth_error_on_repeated_302(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        redirect_resp = MagicMock()
        redirect_resp.status = 302
        redirect_resp.release = AsyncMock()

        api._post = AsyncMock(return_value=redirect_resp)
        api.authenticate = AsyncMock()

        with pytest.raises(KarlstadsenergiAuthError, match="Session expired"):
            await api._request("http://example.com/api")

    @pytest.mark.asyncio
    async def test_raises_api_error_on_non_200_non_redirect(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        bad_resp = MagicMock()
        bad_resp.status = 500
        bad_resp.release = AsyncMock()  # _request awaits resp.release() on non-200
        api._post = AsyncMock(return_value=bad_resp)

        with pytest.raises(KarlstadsenergiApiError, match="API returned status 500"):
            await api._request("http://example.com/api")

    @pytest.mark.asyncio
    async def test_raises_auth_error_on_non_json_content_type(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        html_resp = MagicMock()
        html_resp.status = 200
        html_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        html_resp.release = AsyncMock()

        api._post = AsyncMock(return_value=html_resp)

        with pytest.raises(KarlstadsenergiAuthError, match="Expected JSON"):
            await api._request("http://example.com/api")

    @pytest.mark.asyncio
    async def test_parses_aspnet_wrapper_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True

        ok_resp = MagicMock()
        ok_resp.status = 200
        ok_resp.headers = {"Content-Type": "application/json"}
        ok_resp.json = AsyncMock(return_value={"d": [{"id": 1}]})
        ok_resp.release = AsyncMock()

        api._post = AsyncMock(return_value=ok_resp)

        result = await api._request("http://example.com/api")
        assert result == [{"id": 1}]


# ---------------------------------------------------------------------------
# B6: bankid_initiate
# ---------------------------------------------------------------------------


def _make_bankid_initiate_resp(
    order_ref: str = "ref-abc",
    auto_start_token: str = "token-xyz",
    qr_start_token: str = "qr-tok",
    qr_code_base64: str = "base64data==",
    data_field: str = "",
) -> MagicMock:
    """Return a mock _post response for bankid_initiate."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.release = AsyncMock()
    resp.json = AsyncMock(
        return_value={
            "OrderResponseType": {
                "orderRefField": order_ref,
                "autoStartTokenField": auto_start_token,
                "qrStartTokenField": qr_start_token,
            },
            "QrCodeBase64": qr_code_base64,
            "Data": data_field,
        }
    )
    return resp


class TestBankidInitiate:
    @pytest.mark.asyncio
    async def test_posts_to_grp2_authenticate_url(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = _make_bankid_initiate_resp()
        api._post = AsyncMock(return_value=resp)

        await api.bankid_initiate()

        posted_url: str = api._post.call_args[0][0]
        assert "/api/grp2/Authenticate/" in posted_url
        assert "/bankid/0" in posted_url

    @pytest.mark.asyncio
    async def test_url_contains_transaction_id(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = _make_bankid_initiate_resp()
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_initiate()

        # transaction_id is a uuid4 hex; it must appear in the URL
        tid = result["transaction_id"]
        assert len(tid) == 32
        posted_url: str = api._post.call_args[0][0]
        assert tid in posted_url

    @pytest.mark.asyncio
    async def test_returns_expected_keys(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(return_value=_make_bankid_initiate_resp())

        result = await api.bankid_initiate()

        assert "transaction_id" in result
        assert "order_ref" in result
        assert "auto_start_token" in result
        assert "qr_start_token" in result
        assert "qr_code_base64" in result
        assert "data_field" in result

    @pytest.mark.asyncio
    async def test_maps_order_ref_correctly(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            return_value=_make_bankid_initiate_resp(order_ref="my-order-ref")
        )

        result = await api.bankid_initiate()

        assert result["order_ref"] == "my-order-ref"

    @pytest.mark.asyncio
    async def test_maps_qr_code_base64_correctly(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            return_value=_make_bankid_initiate_resp(qr_code_base64="AAAA/base64==")
        )

        result = await api.bankid_initiate()

        assert result["qr_code_base64"] == "AAAA/base64=="

    @pytest.mark.asyncio
    async def test_missing_order_response_type_returns_empty_strings(self) -> None:
        """If the server returns no OrderResponseType, fields fall back to empty string."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.release = AsyncMock()
        resp.json = AsyncMock(return_value={"QrCodeBase64": "data"})
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_initiate()

        assert result["order_ref"] == ""
        assert result["auto_start_token"] == ""

    @pytest.mark.asyncio
    async def test_explicit_null_order_response_type_returns_empty_strings(
        self,
    ) -> None:
        """OrderResponseType: null must not crash -- fields fall back to empty string."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.release = AsyncMock()
        resp.json = AsyncMock(
            return_value={"OrderResponseType": None, "QrCodeBase64": "data"}
        )
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_initiate()

        assert result["order_ref"] == ""
        assert result["auto_start_token"] == ""


# ---------------------------------------------------------------------------
# B6: bankid_poll
# ---------------------------------------------------------------------------


def _make_bankid_poll_resp(
    progress_status: int = 0,
    has_error: bool = False,
    grp_fault: dict | None = None,
) -> MagicMock:
    """Return a mock _post response for bankid_poll."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.release = AsyncMock()
    payload: dict = {
        "CollectResponseType": {"progressStatusField": progress_status},
        "HasError": has_error,
    }
    if grp_fault is not None:
        payload["GrpFault"] = grp_fault
    resp.json = AsyncMock(return_value=payload)
    return resp


class TestBankidPoll:
    @pytest.mark.asyncio
    async def test_complete_status_returns_zero(self) -> None:
        """BANKID_COMPLETE (0) must be returned as status."""
        from custom_components.karlstadsenergi.api import BANKID_COMPLETE

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(return_value=_make_bankid_poll_resp(progress_status=0))

        result = await api.bankid_poll("order-ref-123")

        assert result["status"] == BANKID_COMPLETE

    @pytest.mark.asyncio
    async def test_pending_user_sign_returns_status_one(self) -> None:
        """BANKID_USER_SIGN (1) is a pending state."""
        from custom_components.karlstadsenergi.api import BANKID_USER_SIGN

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(return_value=_make_bankid_poll_resp(progress_status=1))

        result = await api.bankid_poll("order-ref-123")

        assert result["status"] == BANKID_USER_SIGN

    @pytest.mark.asyncio
    async def test_outstanding_transaction_returns_status_two(self) -> None:
        """BANKID_OUTSTANDING (2) is the initial pending state."""
        from custom_components.karlstadsenergi.api import BANKID_OUTSTANDING

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(return_value=_make_bankid_poll_resp(progress_status=2))

        result = await api.bankid_poll("order-ref-123")

        assert result["status"] == BANKID_OUTSTANDING

    @pytest.mark.asyncio
    async def test_has_error_true_raises_auth_error(self) -> None:
        """HasError=True must raise KarlstadsenergiAuthError."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            return_value=_make_bankid_poll_resp(
                has_error=True,
                grp_fault={"faultStatus": "EXPIRED_TRANSACTION"},
            )
        )

        with pytest.raises(KarlstadsenergiAuthError, match="BankID error"):
            await api.bankid_poll("order-ref-123")

    @pytest.mark.asyncio
    async def test_posts_to_collect_request_url(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(return_value=_make_bankid_poll_resp())

        await api.bankid_poll("my-order-ref")

        posted_url: str = api._post.call_args[0][0]
        assert "/api/grp2/CollectRequest/my-order-ref/bankid" in posted_url

    @pytest.mark.asyncio
    async def test_result_includes_full_data(self) -> None:
        """The 'data' key of the result should contain the raw server response."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = _make_bankid_poll_resp(progress_status=0)
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_poll("ref")

        assert "data" in result
        assert "CollectResponseType" in result["data"]

    @pytest.mark.asyncio
    async def test_missing_progress_status_defaults_to_minus_one(self) -> None:
        """If progressStatusField is absent the status falls back to -1."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.release = AsyncMock()
        resp.json = AsyncMock(
            return_value={"CollectResponseType": {}, "HasError": False}
        )
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_poll("ref")

        assert result["status"] == -1

    @pytest.mark.asyncio
    async def test_explicit_null_collect_response_type_defaults_to_minus_one(
        self,
    ) -> None:
        """CollectResponseType: null must not crash -- status falls back to -1."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.release = AsyncMock()
        resp.json = AsyncMock(
            return_value={"CollectResponseType": None, "HasError": False}
        )
        api._post = AsyncMock(return_value=resp)

        result = await api.bankid_poll("ref")

        assert result["status"] == -1

    @pytest.mark.asyncio
    async def test_explicit_null_grp_fault_raises_with_unknown_code(self) -> None:
        """GrpFault: null must not crash -- fault code falls back to 'unknown'."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.release = AsyncMock()
        resp.json = AsyncMock(
            return_value={
                "CollectResponseType": {"progressStatusField": 0},
                "HasError": True,
                "GrpFault": None,
            }
        )
        api._post = AsyncMock(return_value=resp)

        with pytest.raises(KarlstadsenergiAuthError, match="unknown"):
            await api.bankid_poll("ref")


# ---------------------------------------------------------------------------
# B6: _parse_grp2_json
# ---------------------------------------------------------------------------


class TestParseGrp2Json:
    @pytest.mark.asyncio
    async def test_unwraps_aspnet_d_key_with_json_string(self) -> None:
        """{"d": "<json>"} must be double-decoded."""
        import json as _json

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        inner = [{"FullName": "Anna", "CustomerCode": "12345"}]
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"d": _json.dumps(inner)})

        result = await api._parse_grp2_json(resp)

        assert result == inner

    @pytest.mark.asyncio
    async def test_returns_list_directly_without_d_wrapper(self) -> None:
        """A plain list response (no ASP.NET wrapper) should be returned as-is."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        payload = [{"FullName": "Bob"}]
        resp = MagicMock()
        resp.json = AsyncMock(return_value=payload)

        result = await api._parse_grp2_json(resp)

        assert result == payload

    @pytest.mark.asyncio
    async def test_double_encoded_json_string_is_fully_parsed(self) -> None:
        """d value is a JSON string that is itself valid JSON."""
        import json as _json

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        inner = {"Key": True}
        # d wraps a JSON-string that wraps another JSON-string
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"d": _json.dumps(_json.dumps(inner))})

        result = await api._parse_grp2_json(resp)

        # First unwrap by _parse_aspnet_response -> a json string
        # Second unwrap by explicit json.loads -> dict
        assert result == inner

    @pytest.mark.asyncio
    async def test_string_that_is_not_json_returned_as_string(self) -> None:
        """A non-JSON string inside 'd' must be returned verbatim."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"d": "not-json-{"})

        result = await api._parse_grp2_json(resp)

        assert result == "not-json-{"

    @pytest.mark.asyncio
    async def test_dict_without_d_key_returned_as_is(self) -> None:
        """A plain dict with no 'd' key must pass through unchanged."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        payload = {"foo": "bar"}
        resp = MagicMock()
        resp.json = AsyncMock(return_value=payload)

        result = await api._parse_grp2_json(resp)

        assert result == payload


# ---------------------------------------------------------------------------
# B6: bankid_get_customers
# ---------------------------------------------------------------------------


def _make_resp_with_json(payload: Any) -> MagicMock:
    """Return a _post mock response whose .json() returns payload."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.release = AsyncMock()
    resp.json = AsyncMock(return_value=payload)
    return resp


class TestBankidGetCustomers:
    @pytest.mark.asyncio
    async def test_returns_combined_customers_and_sub_users(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)

        customers_payload = [
            {"FullName": "Kalle Karlsson", "CustomerCode": "C001", "CustomerId": "id1"}
        ]
        sub_users_payload = [
            {
                "ParentFirstName": "Lisa",
                "ParentLastName": "Lindqvist",
                "ParentCode": "C002",
                "ParentIdEncrypted": "id2",
                "UserId": 99,
            }
        ]

        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json(customers_payload),
                _make_resp_with_json(sub_users_payload),
            ]
        )

        accounts = await api.bankid_get_customers("1234567890", "txn-001")

        assert len(accounts) == 2
        assert accounts[0]["full_name"] == "Kalle Karlsson"
        assert accounts[0]["customer_code"] == "C001"
        assert accounts[0]["sub_user_id"] == ""
        assert accounts[1]["full_name"] == "Lisa Lindqvist"
        assert accounts[1]["customer_code"] == "C002"
        assert accounts[1]["sub_user_id"] == "99"

    @pytest.mark.asyncio
    async def test_non_list_customers_response_treated_as_empty(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json({"unexpected": "dict"}),
                _make_resp_with_json([]),
            ]
        )

        accounts = await api.bankid_get_customers("1234567890", "txn-001")

        assert accounts == []

    @pytest.mark.asyncio
    async def test_non_list_sub_users_response_treated_as_empty(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        customers_payload = [
            {"FullName": "Anna", "CustomerCode": "C003", "CustomerId": "id3"}
        ]
        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json(customers_payload),
                _make_resp_with_json(None),
            ]
        )

        accounts = await api.bankid_get_customers("1234567890", "txn-001")

        # Only the main customer; sub-users list falls back to []
        assert len(accounts) == 1
        assert accounts[0]["customer_code"] == "C003"

    @pytest.mark.asyncio
    async def test_sub_user_with_only_last_name(self) -> None:
        """ParentFirstName absent -- full_name should be just the last name."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json([]),
                _make_resp_with_json(
                    [
                        {
                            "ParentFirstName": "",
                            "ParentLastName": "Svensson",
                            "ParentCode": "C004",
                            "ParentIdEncrypted": "id4",
                            "UserId": 7,
                        }
                    ]
                ),
            ]
        )

        accounts = await api.bankid_get_customers("1234567890", "txn-001")

        assert accounts[0]["full_name"] == "Svensson"

    @pytest.mark.asyncio
    async def test_makes_two_post_calls(self) -> None:
        """Exactly two _post calls must be made -- one for customers, one for sub-users."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json([]),
                _make_resp_with_json([]),
            ]
        )

        await api.bankid_get_customers("1234567890", "txn-001")

        assert api._post.call_count == 2

    @pytest.mark.asyncio
    async def test_customer_url_contains_personnummer_and_transaction_id(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        api._post = AsyncMock(
            side_effect=[
                _make_resp_with_json([]),
                _make_resp_with_json([]),
            ]
        )

        await api.bankid_get_customers("1234567890", "txn-abc")

        first_url: str = api._post.call_args_list[0][0][0]
        assert "1234567890" in first_url
        assert "txn-abc" in first_url


# ---------------------------------------------------------------------------
# B6: bankid_login
# ---------------------------------------------------------------------------


def _make_cm_session_get_for_start_aspx(status: int = 200) -> MagicMock:
    """Return a session mock whose .get() works as an async context manager."""
    start_resp = MagicMock()
    start_resp.status = status

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=start_resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=cm)
    mock_session.closed = False
    return mock_session


class TestBankidLogin:
    @pytest.mark.asyncio
    async def test_successful_login_returns_true(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(return_value={"Key": True})
        api._post = AsyncMock(return_value=login_resp)
        api._session = _make_cm_session_get_for_start_aspx(status=200)

        result = await api.bankid_login("1234567890", "cust-id-1", "txn-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_successful_login_sets_authenticated_true(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(return_value={"Key": True})
        api._post = AsyncMock(return_value=login_resp)
        api._session = _make_cm_session_get_for_start_aspx(status=200)

        await api.bankid_login("1234567890", "cust-id-1", "txn-001")

        assert api._authenticated is True

    @pytest.mark.asyncio
    async def test_key_false_raises_auth_error(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(
            return_value={"Key": False, "Value": "invalid session"}
        )
        api._post = AsyncMock(return_value=login_resp)

        with pytest.raises(KarlstadsenergiAuthError, match="BankID login failed"):
            await api.bankid_login("1234567890", "cust-id-1", "txn-001")

    @pytest.mark.asyncio
    async def test_start_aspx_redirect_raises_auth_error(self) -> None:
        """302 from start.aspx should abort with KarlstadsenergiAuthError."""
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(return_value={"Key": True})
        api._post = AsyncMock(return_value=login_resp)
        api._session = _make_cm_session_get_for_start_aspx(status=302)

        with pytest.raises(
            KarlstadsenergiAuthError, match="Session initialization failed"
        ):
            await api.bankid_login("1234567890", "cust-id-1", "txn-001")

    @pytest.mark.asyncio
    async def test_posts_to_grp2_login_url(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(return_value={"Key": True})
        api._post = AsyncMock(return_value=login_resp)
        api._session = _make_cm_session_get_for_start_aspx(status=200)

        await api.bankid_login("1234567890", "cust-id-1", "txn-001")

        posted_url: str = api._post.call_args[0][0]
        assert "/api/grp2/Login/" in posted_url

    @pytest.mark.asyncio
    async def test_url_encodes_customer_id_as_base64(self) -> None:
        """customer_id must appear in the URL as base64."""
        import base64 as _b64

        api = KarlstadsenergiApi("1234567890", AUTH_BANKID)
        login_resp = MagicMock()
        login_resp.raise_for_status = MagicMock()
        login_resp.release = AsyncMock()
        login_resp.json = AsyncMock(return_value={"Key": True})
        api._post = AsyncMock(return_value=login_resp)
        api._session = _make_cm_session_get_for_start_aspx(status=200)

        await api.bankid_login("1234567890", "my-customer-id", "txn-001")

        expected_b64 = _b64.b64encode(b"my-customer-id").decode("ascii")
        posted_url: str = api._post.call_args[0][0]
        assert expected_b64 in posted_url


# ---------------------------------------------------------------------------
# H12: async_get_flex_services
# ---------------------------------------------------------------------------


class TestAsyncGetFlexServices:
    @pytest.mark.asyncio
    async def test_returns_list_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ServiceId": 1, "Name": "Mat- och restavfall"}]
        api._request = AsyncMock(return_value=expected)

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        result = await api.async_get_flex_services()

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_is_not_list(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={"unexpected": "dict"})

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        result = await api.async_get_flex_services()

        assert result == []

    @pytest.mark.asyncio
    async def test_triggers_auth_when_not_authenticated(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = False
        api.authenticate = AsyncMock(
            side_effect=lambda: setattr(api, "_authenticated", True) or None
        )
        api._request = AsyncMock(return_value=[])

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        await api.async_get_flex_services()

        api.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_page_visit_connection_error_propagates(self) -> None:
        """Connection error from the flex page GET propagates as KarlstadsenergiConnectionError."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[{"ServiceId": 2}])

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("network error"))
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        with pytest.raises(KarlstadsenergiConnectionError):
            await api.async_get_flex_services()


# ---------------------------------------------------------------------------
# H12: async_get_consumption
# ---------------------------------------------------------------------------


class TestAsyncGetConsumption:
    def _make_page_visit_session(self) -> MagicMock:
        """Session mock that supports two sequential GET context managers."""
        mock_session = MagicMock()
        mock_session.closed = False

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        return mock_session

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"ConsumptionViewModel": {"value": 42}}
        api._request = AsyncMock(return_value=expected)
        api._session = self._make_page_visit_session()

        result = await api.async_get_consumption()

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_result_is_not_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[1, 2, 3])
        api._session = self._make_page_visit_session()

        result = await api.async_get_consumption()

        assert result == {}

    @pytest.mark.asyncio
    async def test_triggers_auth_when_not_authenticated(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = False
        api.authenticate = AsyncMock(
            side_effect=lambda: setattr(api, "_authenticated", True) or None
        )
        api._request = AsyncMock(return_value={})
        api._session = self._make_page_visit_session()

        await api.async_get_consumption()

        api.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_none_result(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=None)
        api._session = self._make_page_visit_session()

        result = await api.async_get_consumption()

        assert result == {}


# ---------------------------------------------------------------------------
# H12: async_get_hourly_consumption
# ---------------------------------------------------------------------------


class TestAsyncGetHourlyConsumption:
    @pytest.mark.asyncio
    async def test_sets_interval_to_hour(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={"series": []})

        await api.async_get_hourly_consumption(
            {"Interval": "MONTH", "IsPageLoad": True}
        )

        _, kwargs = api._request.call_args
        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["Interval"] == "HOUR"

    @pytest.mark.asyncio
    async def test_sets_interval_enum_to_four(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_hourly_consumption({})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["IntervalEnum"] == 4

    @pytest.mark.asyncio
    async def test_sets_is_page_load_false(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_hourly_consumption({"IsPageLoad": True})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["IsPageLoad"] is False

    @pytest.mark.asyncio
    async def test_does_not_mutate_input_model(self) -> None:
        """Original model dict must not be modified in place."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        original = {"Interval": "MONTH", "IsPageLoad": True}
        await api.async_get_hourly_consumption(original)

        assert original["Interval"] == "MONTH"
        assert original["IsPageLoad"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_result_is_not_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=["not", "a", "dict"])

        result = await api.async_get_hourly_consumption({})

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"series": [{"id": "kWh", "values": [1.0, 2.0]}]}
        api._request = AsyncMock(return_value=expected)

        result = await api.async_get_hourly_consumption({})

        assert result == expected


# ---------------------------------------------------------------------------
# H12: async_get_contract_details
# ---------------------------------------------------------------------------


class TestAsyncGetContractDetails:
    @pytest.mark.asyncio
    async def test_returns_list_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = [{"ContractId": "abc", "UtilityName": "Elnät - Nätavtal"}]
        api._request = AsyncMock(return_value=expected)

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        result = await api.async_get_contract_details(["site-1"])

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_is_not_list(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={"not": "a list"})

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        result = await api.async_get_contract_details(["site-1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_site_ids_in_request_body(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[])

        mock_session = MagicMock()
        mock_session.closed = False
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)
        api._session = mock_session

        await api.async_get_contract_details(["site-A", "site-B"])

        _, body = api._request.call_args[0]
        assert body == {"usePlaces": ["site-A", "site-B"]}

    @pytest.mark.asyncio
    async def test_visits_contracts_page_before_request(self) -> None:
        """The contracts page GET must be called before _request."""
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        call_order: list[str] = []

        async def _fake_request(*_args: Any, **_kwargs: Any) -> list:
            call_order.append("request")
            return []

        api._request = _fake_request  # type: ignore[assignment]

        mock_session = MagicMock()
        mock_session.closed = False

        def _track_get(url: str, **_kw: Any) -> Any:
            call_order.append(f"get:{url}")
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock())
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        mock_session.get = _track_get
        api._session = mock_session

        await api.async_get_contract_details(["site-1"])

        # Page visit must precede the _request call
        assert len(call_order) == 2
        assert "get:" in call_order[0]
        assert call_order[1] == "request"


# ---------------------------------------------------------------------------
# H12: async_get_fee_consumption
# ---------------------------------------------------------------------------


class TestAsyncGetFeeConsumption:
    @pytest.mark.asyncio
    async def test_sets_is_fee_type_request_true(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_fee_consumption({})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["IsFeeTypeRequest"] is True

    @pytest.mark.asyncio
    async def test_sets_target_unit_sek(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_fee_consumption({})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["TargetUnit"] == "SEK"

    @pytest.mark.asyncio
    async def test_sets_interval_to_month(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_fee_consumption({"Interval": "HOUR"})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["Interval"] == "MONTH"

    @pytest.mark.asyncio
    async def test_sets_interval_enum_to_two(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_fee_consumption({})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert sent_model["IntervalEnum"] == 2

    @pytest.mark.asyncio
    async def test_includes_invoice_in_loadoptions(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_fee_consumption({})

        import json as _json

        sent_model = _json.loads(api._request.call_args[0][1]["data"])
        assert "Invoice" in sent_model["Loadoptions"]

    @pytest.mark.asyncio
    async def test_does_not_mutate_input_model(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        original = {"Interval": "HOUR", "IsPageLoad": True}
        await api.async_get_fee_consumption(original)

        assert original["Interval"] == "HOUR"
        assert original["IsPageLoad"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_result_is_not_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=[1, 2, 3])

        result = await api.async_get_fee_consumption({})

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"series": [{"id": "SUM", "values": [100.0]}]}
        api._request = AsyncMock(return_value=expected)

        result = await api.async_get_fee_consumption({})

        assert result == expected


# ---------------------------------------------------------------------------
# H12: async_get_service_info
# ---------------------------------------------------------------------------


class TestAsyncGetServiceInfo:
    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        expected = {"MeterNumber": "1234", "Address": "Testgatan 1"}
        api._request = AsyncMock(return_value=expected)

        result = await api.async_get_service_info()

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_result_is_not_dict(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=["not", "a", "dict"])

        result = await api.async_get_service_info()

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_none_result(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value=None)

        result = await api.async_get_service_info()

        assert result == {}

    @pytest.mark.asyncio
    async def test_calls_request_with_service_info_url(self) -> None:
        from custom_components.karlstadsenergi.const import BASE_URL

        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        api._authenticated = True
        api._request = AsyncMock(return_value={})

        await api.async_get_service_info()

        called_url: str = api._request.call_args[0][0]
        assert "GetServiceInfo" in called_url
        assert BASE_URL in called_url
