"""Tests for api.py -- _parse_aspnet_response and KarlstadsenergiApi."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.karlstadsenergi.api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    KarlstadsenergiApi,
    KarlstadsenergiApiError,
    KarlstadsenergiAuthError,
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


class TestAsyncHeartbeat:
    @pytest.mark.asyncio
    async def test_returns_true_on_200(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_resp = MagicMock()
        mock_resp.status = 200

        mock_session = MagicMock()
        # aiohttp session.get() can be awaited directly (returns _RequestContextManager)
        mock_session.get = AsyncMock(return_value=mock_resp)
        mock_session.closed = False
        api._session = mock_session

        result = await api.async_heartbeat()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_session = MagicMock()
        mock_session.get = AsyncMock(side_effect=Exception("timeout"))
        mock_session.closed = False
        api._session = mock_session

        result = await api.async_heartbeat()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_non_200(self) -> None:
        api = KarlstadsenergiApi("1234567890", AUTH_PASSWORD, "pass")
        mock_resp = MagicMock()
        mock_resp.status = 503

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=mock_resp)
        mock_session.closed = False
        api._session = mock_session

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

        api._post = AsyncMock(return_value=ok_resp)

        result = await api._request("http://example.com/api")
        assert result == [{"id": 1}]
