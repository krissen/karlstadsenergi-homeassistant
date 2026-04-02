"""API client for Karlstadsenergi customer portal."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    BASE_URL,
    URL_CONTRACT_DETAILS,
    URL_FLEX_DATES,
    URL_FLEX_SERVICES,
    URL_LOGIN,
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
    """API client for Karlstadsenergi customer portal.

    # This integration uses its own aiohttp.ClientSession rather than
    # async_get_clientsession(hass) because it needs a dedicated CookieJar
    # for session-based authentication (ASP.NET_SessionId + .PORTALAUTH).
    # HA's shared session does not support per-integration cookie state.
    """

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
        self._auth_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create session if needed.

        Serialized with a lock to prevent concurrent callers (heartbeat
        + coordinators) from creating duplicate sessions.
        """
        async with self._session_lock:
            if self._session is None or self._session.closed:
                jar = aiohttp.CookieJar()
                self._session = aiohttp.ClientSession(cookie_jar=jar)
                self._authenticated = False
                if self._saved_cookies:
                    for name, value in self._saved_cookies.items():
                        jar.update_cookies(
                            {name: value},
                            URL(BASE_URL),
                        )
                    self._authenticated = True
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
        self,
        url: str,
        json_data: Any = None,
        **kwargs: Any,
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
                f"Connection error: {type(err).__name__}"
            ) from err

    # ── Password authentication ──────────────────────────────

    async def authenticate_password(self) -> bool:
        """Authenticate with customer number and password."""
        # Clear any stale cookies before fresh login
        session = await self._ensure_session()
        session.cookie_jar.clear()

        resp = await self._post(
            URL_LOGIN,
            {"user": self._personnummer, "password": self._password, "captcha": ""},
        )
        try:
            resp.raise_for_status()
            data = await resp.json()
        finally:
            await resp.release()

        result = _parse_aspnet_response(data)
        if isinstance(result, dict):
            # Result can be True (boolean) or "OK" (string)
            status = result.get("Result")
            login_status = result.get("LoginResultStatus")
        else:
            status = result
            login_status = None

        if status is not True and status != "OK":
            self._authenticated = False
            raise KarlstadsenergiAuthError(
                f"Authentication failed: Result={status}, LoginResultStatus={login_status}"
            )

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
        try:
            resp.raise_for_status()
            data = await resp.json()
        finally:
            await resp.release()

        order_resp = data.get("OrderResponseType") or {}
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
        try:
            resp.raise_for_status()
            data = await resp.json()
        finally:
            await resp.release()

        collect = data.get("CollectResponseType") or {}
        status = collect.get("progressStatusField", -1)

        if data.get("HasError"):
            fault = data.get("GrpFault") or {}
            fault_code = fault.get("faultStatusField", "unknown")
            # Only log the fault code, not the full dict (may contain PII)
            raise KarlstadsenergiAuthError(f"BankID error: code={fault_code}")

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
        self,
        personnummer: str,
        transaction_id: str,
    ) -> list[dict[str, Any]]:
        """Get customers and sub-users for the authenticated person.

        Returns a combined list of accounts to choose from, each with:
        - FullName, CustomerCode, CustomerId, SubUserId (optional)

        Note: The upstream API requires personnummer in the URL path.
        This is a design decision in the Karlstadsenergi portal, not ours.
        All requests use HTTPS so the path is encrypted in transit.
        """
        # Get main customers
        url = (
            f"{BASE_URL}/api/grp2/GetCustomerByPinCode/{personnummer}/{transaction_id}"
        )
        resp = await self._post(url)
        try:
            resp.raise_for_status()
            customers = await self._parse_grp2_json(resp)
        finally:
            await resp.release()
        if not isinstance(customers, list):
            customers = []

        # Get sub-users
        url_sub = f"{BASE_URL}/api/subuser/GetSubUsersByPinCode/{personnummer}"
        resp = await self._post(url_sub)
        try:
            resp.raise_for_status()
            sub_users = await self._parse_grp2_json(resp)
        finally:
            await resp.release()
        if not isinstance(sub_users, list):
            sub_users = []

        # Build unified account list
        accounts: list[dict[str, Any]] = []
        for c in customers:
            accounts.append(
                {
                    "full_name": c.get("FullName", ""),
                    "customer_code": c.get("CustomerCode", ""),
                    "customer_id": c.get("CustomerId", ""),
                    "sub_user_id": "",
                }
            )

        # Add sub-users (other people's accounts you have access to)
        for su in sub_users:
            first = su.get("ParentFirstName", "")
            last = su.get("ParentLastName", "")
            name = f"{first} {last}".strip() if first else last
            accounts.append(
                {
                    "full_name": name,
                    "customer_code": su.get("ParentCode", ""),
                    "customer_id": su.get("ParentIdEncrypted", ""),
                    "sub_user_id": str(su.get("UserId", "")),
                }
            )

        return accounts

    async def bankid_login(
        self,
        personnummer: str,
        customer_id: str,
        transaction_id: str,
        sub_user_id: str = "",
    ) -> bool:
        """Complete BankID login for a selected account."""
        b64_customer_id = base64.b64encode(
            customer_id.encode("utf-8"),
        ).decode("ascii")

        url_login = (
            f"{BASE_URL}/api/grp2/Login"
            f"/{personnummer}/{b64_customer_id}"
            f"/{transaction_id}/{sub_user_id}"
        )
        resp = await self._post(url_login)
        try:
            resp.raise_for_status()
            result = await resp.json()
        finally:
            await resp.release()

        if result.get("Key") is True:
            # Navigate to start page to initialize the session view
            # (server requires this before API calls work)
            session = await self._ensure_session()
            async with session.get(
                f"{BASE_URL}/start.aspx",
                headers={"X-Requested-With": "XMLHttpRequest"},
            ) as start_resp:
                if start_resp.status in (301, 302, 401, 403):
                    raise KarlstadsenergiAuthError(
                        f"Session initialization failed (status {start_resp.status})"
                    )

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
        """Authenticate using configured method.

        Serialized with a lock to prevent concurrent calls from
        overwriting cookies mid-sequence when multiple coordinators
        share this API instance.
        """
        async with self._auth_lock:
            if self._authenticated:
                return True
            if self._auth_method == AUTH_PASSWORD:
                return await self.authenticate_password()
            return await self.bankid_authenticate()

    # ── Authenticated API requests ───────────────────────────

    async def _visit_pages(
        self,
        session: aiohttp.ClientSession,
        pages: tuple[str, ...],
    ) -> None:
        """Visit ASPX pages to initialize server-side state."""
        for page in pages:
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    async with session.get(f"{BASE_URL}/{page}"):
                        pass
            except asyncio.TimeoutError as err:
                raise KarlstadsenergiConnectionError(
                    f"Timeout visiting {page}"
                ) from err
            except aiohttp.ClientError as err:
                raise KarlstadsenergiConnectionError(
                    f"Connection error visiting {page}: {err}"
                ) from err

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

        try:
            # 302 redirect or 401 = session expired
            if resp.status in (301, 302, 401, 403):
                if retry_auth:
                    self._authenticated = False
                    await self.authenticate()
                    return await self._request(url, json_data, retry_auth=False)
                raise KarlstadsenergiAuthError("Session expired and re-auth failed")

            if resp.status != 200:
                raise KarlstadsenergiApiError(f"API returned status {resp.status}")

            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type:
                raise KarlstadsenergiAuthError(
                    f"Expected JSON, got {content_type} (likely session expired)"
                )

            data = await resp.json()
            return _parse_aspnet_response(data)
        finally:
            await resp.release()

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
        """Get all waste collection services.

        Requires visiting the flex page first to initialize server state.
        """
        if not self._authenticated:
            await self.authenticate()

        pages = ("flex/flexservices.aspx",)
        session = await self._ensure_session()
        await self._visit_pages(session, pages)

        try:
            result = await self._request(URL_FLEX_SERVICES, retry_auth=False)
        except KarlstadsenergiAuthError:
            self._authenticated = False
            await self.authenticate()
            session = await self._ensure_session()
            await self._visit_pages(session, pages)
            result = await self._request(URL_FLEX_SERVICES, retry_auth=False)

        if not isinstance(result, list):
            return []
        return result

    async def async_get_flex_dates(
        self,
        service_ids: list[int],
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
        """Get electricity consumption data.

        Visits start.aspx + consumption.aspx to initialize server state,
        then calls GetConsumptionViewModelOnLoad.
        """
        if not self._authenticated:
            await self.authenticate()

        pages = ("start.aspx", "consumption/consumption.aspx")
        session = await self._ensure_session()
        await self._visit_pages(session, pages)

        url = f"{BASE_URL}/Consumption/Consumption.aspx/GetConsumptionViewModelOnLoad"
        try:
            result = await self._request(url, retry_auth=False)
        except KarlstadsenergiAuthError:
            self._authenticated = False
            await self.authenticate()
            session = await self._ensure_session()
            await self._visit_pages(session, pages)
            result = await self._request(url, retry_auth=False)

        if not isinstance(result, dict):
            return {}
        return result

    async def async_get_hourly_consumption(
        self,
        consumption_model: dict[str, Any],
    ) -> dict[str, Any]:
        """Get hourly consumption using the consumption model from OnLoad.

        Modifies the model to request hourly interval.
        """
        model = {**consumption_model}
        model["Interval"] = "HOUR"
        model["IntervalEnum"] = 4
        model["IsPageLoad"] = False

        url = f"{BASE_URL}/Consumption/Consumption.aspx/GetConsumption"
        result = await self._request(url, {"data": json.dumps(model)})
        if not isinstance(result, dict):
            return {}
        return result

    async def async_get_service_info(self) -> dict[str, Any]:
        """Get service/meter info."""
        url = f"{BASE_URL}/consumption/consumption.aspx/GetServiceInfo"
        result = await self._request(url)
        if not isinstance(result, dict):
            return {}
        return result

    async def async_get_contract_details(
        self,
        site_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Get contract details for given site/use-place IDs.

        Visits the contracts page first to initialize server-side state.
        """
        if not self._authenticated:
            await self.authenticate()

        pages = ("contract/contracts.aspx",)
        session = await self._ensure_session()
        await self._visit_pages(session, pages)

        try:
            result = await self._request(
                URL_CONTRACT_DETAILS,
                {"usePlaces": site_ids},
                retry_auth=False,
            )
        except KarlstadsenergiAuthError:
            self._authenticated = False
            await self.authenticate()
            session = await self._ensure_session()
            await self._visit_pages(session, pages)
            result = await self._request(
                URL_CONTRACT_DETAILS,
                {"usePlaces": site_ids},
                retry_auth=False,
            )

        if not isinstance(result, list):
            return []
        return result

    async def async_get_fee_consumption(
        self,
        consumption_model: dict[str, Any],
    ) -> dict[str, Any]:
        """Get fee-type consumption breakdown (SEK by month).

        Modifies the consumption model to request invoice/fee data.
        The caller is expected to set StartDate for the desired period.
        """
        model = {**consumption_model}
        model["IsFeeTypeRequest"] = True
        model["Loadoptions"] = ["Invoice"]
        model["TargetUnit"] = "SEK"
        model["Interval"] = "MONTH"
        model["IntervalEnum"] = 2
        model["IsPageLoad"] = False

        url = f"{BASE_URL}/Consumption/Consumption.aspx/GetConsumption"
        result = await self._request(url, {"data": json.dumps(model)})
        if not isinstance(result, dict):
            return {}
        return result

    async def async_heartbeat(self) -> bool:
        """Send heartbeat to keep session alive."""
        session = await self._ensure_session()
        try:
            async with asyncio.timeout(10):
                async with session.get(
                    f"{BASE_URL}/heart.beat",
                    headers=REQUEST_HEADERS,
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def async_close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._authenticated = False
