"""API client for Karlstadsenergi customer portal."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .const import (
    URL_CONSUMPTION,
    URL_FLEX_DATES,
    URL_FLEX_SERVICES,
    URL_LOGIN,
    URL_SERVICE_INFO,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
}


class KarlstadsenergiApiError(Exception):
    """Base exception for Karlstadsenergi API errors."""


class KarlstadsenergiAuthError(KarlstadsenergiApiError):
    """Authentication failed."""


class KarlstadsenergiConnectionError(KarlstadsenergiApiError):
    """Connection error."""


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

    def __init__(self, customer_number: str, password: str) -> None:
        self._customer_number = customer_number
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._authenticated = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create session if needed."""
        if self._session is None or self._session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
            self._authenticated = False
        return self._session

    async def authenticate(self) -> bool:
        """Authenticate with customer number and password.

        Returns True on success, raises KarlstadsenergiAuthError on failure.
        """
        session = await self._ensure_session()
        payload = {
            "user": self._customer_number,
            "password": self._password,
            "captcha": "",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await session.post(
                    URL_LOGIN,
                    json=payload,
                    headers=REQUEST_HEADERS,
                )
                resp.raise_for_status()
                data = await resp.json()
        except asyncio.TimeoutError as err:
            raise KarlstadsenergiConnectionError(
                "Timeout connecting to Karlstadsenergi"
            ) from err
        except aiohttp.ClientError as err:
            raise KarlstadsenergiConnectionError(
                f"Connection error: {err}"
            ) from err

        result = _parse_aspnet_response(data)
        if isinstance(result, dict):
            status = result.get("Result", "")
        else:
            status = str(result) if result else ""

        if status != "OK":
            self._authenticated = False
            raise KarlstadsenergiAuthError(
                f"Authentication failed: {status}"
            )

        self._authenticated = True
        _LOGGER.debug("Successfully authenticated with Karlstadsenergi")
        return True

    async def _request(
        self,
        url: str,
        json_data: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Make an authenticated API request.

        Automatically re-authenticates on session expiry (302 redirect or 401).
        """
        session = await self._ensure_session()

        if not self._authenticated:
            await self.authenticate()

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await session.post(
                    url,
                    json=json_data if json_data is not None else {},
                    headers=REQUEST_HEADERS,
                    allow_redirects=False,
                )
        except asyncio.TimeoutError as err:
            raise KarlstadsenergiConnectionError(
                "Timeout connecting to Karlstadsenergi"
            ) from err
        except aiohttp.ClientError as err:
            raise KarlstadsenergiConnectionError(
                f"Connection error: {err}"
            ) from err

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

        data = await resp.json()
        return _parse_aspnet_response(data)

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

    async def async_close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._authenticated = False
