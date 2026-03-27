"""API client for Karlstadsenergi customer portal."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    URL_CONSUMPTION,
    URL_FLEX_DATES,
    URL_FLEX_SERVICES,
    URL_LOGIN,
    URL_SERVICE_INFO,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
BANKID_POLL_INTERVAL = 2
BANKID_POLL_TIMEOUT = 60
REQUEST_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
}

# BankID progress status codes
BANKID_COMPLETE = 0
BANKID_USER_SIGN = 1
BANKID_OUTSTANDING = 2

# Auth methods
AUTH_PASSWORD = "password"
AUTH_BANKID = "bankid"


class KarlstadsenergiApiError(Exception):
    """Base exception for Karlstadsenergi API errors."""


class KarlstadsenergiAuthError(KarlstadsenergiApiError):
    """Authentication failed."""


class KarlstadsenergiConnectionError(KarlstadsenergiApiError):
    """Connection error."""


class BankIdPendingError(KarlstadsenergiApiError):
    """BankID authentication is pending user action."""


def _parse_aspnet_response(data: dict[str, Any]) -> Any:
    """Parse ASP.NET WebMethod response wrapper.

    ASP.NET returns {"d": <value>} where value can be:
    - A JSON string that needs double-parsing
    - A direct object/list
    """
    value = data.get("d")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class KarlstadsenergiApi:
    """API client for Karlstadsenergi customer portal."""

    def __init__(
        self,
        personnummer: str,
        auth_method: str = AUTH_BANKID,
        password: str = "",
    ) -> None:
        self._personnummer = personnummer
        self._auth_method = auth_method
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._authenticated = False
        self._saved_cookies: dict[str, str] | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create session if needed."""
        if self._session is None or self._session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
            self._authenticated = False
            # Restore saved cookies if available
            if self._saved_cookies:
                from yarl import URL
                for name, value in self._saved_cookies.items():
                    jar.update_cookies(
                        {name: value},
                        URL(BASE_URL),
                    )
                self._authenticated = True
                self._saved_cookies = None
                _LOGGER.debug("Restored session from saved cookies")
        return self._session

    def get_session_cookies(self) -> dict[str, str]:
        """Export current session cookies for persistence."""
        if not self._session or self._session.closed:
            return {}
        cookies = {}
        for cookie in self._session.cookie_jar:
            if cookie.key in ("ASP.NET_SessionId", ".PORTALAUTH"):
                cookies[cookie.key] = cookie.value
        return cookies

    def set_session_cookies(self, cookies: dict[str, str]) -> None:
        """Set saved cookies to restore on next session creation."""
        self._saved_cookies = cookies

    async def _post(
        self, url: str, json_data: Any = None, **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """POST with timeout and error handling."""
        session = await self._ensure_session()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await session.post(
                    url,
                    json=json_data,
                    headers=REQUEST_HEADERS,
                    **kwargs,
                )
        except asyncio.TimeoutError as err:
            raise KarlstadsenergiConnectionError(
                "Timeout connecting to Karlstadsenergi"
            ) from err
        except aiohttp.ClientError as err:
            raise KarlstadsenergiConnectionError(
                f"Connection error: {err}"
            ) from err

    # ── Password authentication ──────────────────────────────

    async def authenticate_password(self) -> bool:
        """Authenticate with customer number and password."""
        resp = await self._post(
            URL_LOGIN,
            {"user": self._personnummer, "password": self._password, "captcha": ""},
        )
        resp.raise_for_status()
        data = await resp.json()

        result = _parse_aspnet_response(data)
        status = result.get("Result", "") if isinstance(result, dict) else str(result)

        if status != "OK":
            self._authenticated = False
            raise KarlstadsenergiAuthError(f"Authentication failed: {status}")

        self._authenticated = True
        _LOGGER.debug("Password authentication successful")
        return True

    # ── BankID authentication ────────────────────────────────

    async def bankid_initiate(self) -> dict[str, str]:
        """Start BankID authentication.

        Returns dict with transaction_id, order_ref, auto_start_token,
        and qr_code_base64 (PNG image for scanning).
        """
        transaction_id = uuid.uuid4().hex
        url = f"{BASE_URL}/api/grp2/Authenticate/{transaction_id}/bankid/0"
        resp = await self._post(url)
        resp.raise_for_status()
        data = await resp.json()

        order_resp = data.get("OrderResponseType", {})
        return {
            "transaction_id": transaction_id,
            "order_ref": order_resp.get("orderRefField", ""),
            "auto_start_token": order_resp.get("autoStartTokenField", ""),
            "qr_start_token": order_resp.get("qrStartTokenField", ""),
            "qr_code_base64": data.get("QrCodeBase64", ""),
            "data_field": data.get("Data", ""),
        }

    async def bankid_poll(self, order_ref: str) -> dict[str, Any]:
        """Poll BankID collect status once.

        Returns dict with status (int) and full response.
        """
        url = f"{BASE_URL}/api/grp2/CollectRequest/{order_ref}/bankid"
        resp = await self._post(url)
        resp.raise_for_status()
        data = await resp.json()

        collect = data.get("CollectResponseType", {})
        status = collect.get("progressStatusField", -1)

        if data.get("HasError"):
            fault = data.get("GrpFault", {})
            raise KarlstadsenergiAuthError(
                f"BankID error: {fault}"
            )

        return {"status": status, "data": data}

    async def _parse_grp2_json(self, resp: aiohttp.ClientResponse) -> Any:
        """Parse GRP2 response (may or may not have ASP.NET wrapper)."""
        raw = await resp.json()
        data = raw
        if isinstance(raw, dict) and "d" in raw:
            data = _parse_aspnet_response(raw)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return data

    async def bankid_get_customers(
        self, personnummer: str, transaction_id: str,
    ) -> list[dict[str, Any]]:
        """Get customers and sub-users for the authenticated person.

        Returns a combined list of accounts to choose from, each with:
        - FullName, CustomerCode, CustomerId, SubUserId (optional)
        """
        # Get main customers
        url = (
            f"{BASE_URL}/api/grp2/GetCustomerByPinCode"
            f"/{personnummer}/{transaction_id}"
        )
        resp = await self._post(url)
        resp.raise_for_status()
        customers = await self._parse_grp2_json(resp)
        if not isinstance(customers, list):
            customers = []
        _LOGGER.debug("Customers: %s", str(customers)[:300])

        # Get sub-users
        url_sub = f"{BASE_URL}/api/subuser/GetSubUsersByPinCode/{personnummer}"
        resp = await self._post(url_sub)
        resp.raise_for_status()
        sub_users = await self._parse_grp2_json(resp)
        if not isinstance(sub_users, list):
            sub_users = []
        _LOGGER.debug("SubUsers: %s", str(sub_users)[:500])

        # Build unified account list
        accounts: list[dict[str, Any]] = []
        for c in customers:
            accounts.append({
                "full_name": c.get("FullName", ""),
                "customer_code": c.get("CustomerCode", ""),
                "customer_id": c.get("CustomerId", ""),
                "sub_user_id": "",
            })

        # Add sub-users (other people's accounts you have access to)
        for su in sub_users:
            first = su.get("ParentFirstName", "")
            last = su.get("ParentLastName", "")
            name = f"{first} {last}".strip() if first else last
            accounts.append({
                "full_name": name,
                "customer_code": su.get("ParentCode", ""),
                "customer_id": su.get("ParentIdEncrypted", ""),
                "sub_user_id": str(su.get("UserId", "")),
            })

        return accounts

    async def bankid_login(
        self,
        personnummer: str,
        customer_id: str,
        transaction_id: str,
        sub_user_id: str = "",
    ) -> bool:
        """Complete BankID login for a selected account."""
        import base64
        b64_customer_id = base64.b64encode(
            customer_id.encode("utf-8"),
        ).decode("ascii")

        url_login = (
            f"{BASE_URL}/api/grp2/Login"
            f"/{personnummer}/{b64_customer_id}"
            f"/{transaction_id}/{sub_user_id}"
        )
        resp = await self._post(url_login)
        resp.raise_for_status()
        result = await resp.json()
        _LOGGER.debug("Login response: %s", result)

        if result.get("Key") is True:
            # Navigate to start page to initialize the session view
            # (server requires this before API calls work)
            session = await self._ensure_session()
            await session.get(
                f"{BASE_URL}/start.aspx",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            _LOGGER.debug("Visited start.aspx to initialize session")

            self._authenticated = True
            _LOGGER.debug("BankID authentication successful")
            return True

        raise KarlstadsenergiAuthError(
            f"BankID login failed: {result.get('Value', 'unknown')}"
        )

    async def bankid_authenticate(self) -> bool:
        """Full BankID flow (non-interactive, for re-auth).

        Cannot be used for initial setup -- requires interactive QR scan.
        Raises KarlstadsenergiAuthError always for BankID.
        """
        raise KarlstadsenergiAuthError(
            "BankID requires interactive authentication (QR scan). "
            "Session cookies must be restored instead."
        )

    # ── Unified authenticate ─────────────────────────────────

    async def authenticate(self) -> bool:
        """Authenticate using configured method."""
        if self._auth_method == AUTH_PASSWORD:
            return await self.authenticate_password()
        return await self.bankid_authenticate()

    # ── Authenticated API requests ───────────────────────────

    async def _request(
        self,
        url: str,
        json_data: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Make an authenticated API request.

        Automatically re-authenticates on session expiry (302 redirect or 401).
        """
        if not self._authenticated:
            await self.authenticate()

        resp = await self._post(
            url,
            json_data if json_data is not None else {},
            allow_redirects=False,
        )

        # 302 redirect or 401 = session expired
        if resp.status in (301, 302, 401, 403):
            if retry_auth:
                _LOGGER.debug("Session expired, re-authenticating")
                self._authenticated = False
                await self.authenticate()
                return await self._request(url, json_data, retry_auth=False)
            raise KarlstadsenergiAuthError("Session expired and re-auth failed")

        if resp.status != 200:
            raise KarlstadsenergiApiError(
                f"API returned status {resp.status}"
            )

        content_type = resp.headers.get("Content-Type", "")
        if "json" not in content_type:
            text = await resp.text()
            _LOGGER.debug("Non-JSON response from %s: %s", url, text[:200])
            raise KarlstadsenergiAuthError(
                f"Expected JSON, got {content_type} (likely session expired)"
            )

        data = await resp.json()
        return _parse_aspnet_response(data)

    async def async_get_next_flex_dates(self) -> list[dict[str, Any]]:
        """Get next pickup dates (simple summary from start page).

        Returns list of {Date, Address, Type, Size}.
        """
        result = await self._request(
            f"{BASE_URL}/Start.aspx/GetNextFlexFetchDate",
        )
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(result, list):
            return []
        return result

    async def async_get_flex_services(self) -> list[dict[str, Any]]:
        """Get all waste collection services."""
        result = await self._request(URL_FLEX_SERVICES)
        if not isinstance(result, list):
            return []
        return result

    async def async_get_flex_dates(
        self, service_ids: list[int],
    ) -> dict[str, str]:
        """Get next planned pickup dates for given service IDs."""
        if not service_ids:
            return {}
        ids_str = "|".join(str(sid) for sid in service_ids)
        result = await self._request(
            URL_FLEX_DATES,
            {"flexServiceIds": ids_str},
        )
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return {}
        if not isinstance(result, dict):
            return {}
        return result

    async def async_get_consumption(self) -> dict[str, Any]:
        """Get electricity consumption data."""
        result = await self._request(URL_CONSUMPTION)
        if not isinstance(result, dict):
            return {}
        return result

    async def async_get_service_info(self) -> dict[str, Any]:
        """Get service/meter info."""
        result = await self._request(URL_SERVICE_INFO)
        if not isinstance(result, dict):
            return {}
        return result

    async def async_heartbeat(self) -> bool:
        """Send heartbeat to keep session alive."""
        session = await self._ensure_session()
        try:
            async with asyncio.timeout(10):
                resp = await session.get(f"{BASE_URL}/heart.beat")
                return resp.status == 200
        except Exception:
            return False

    async def async_close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._authenticated = False
