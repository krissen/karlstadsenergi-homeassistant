"""Config flow for Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    BANKID_COMPLETE,
    BANKID_OUTSTANDING,
    BANKID_USER_SIGN,
    KarlstadsenergiAccountLockedError,
    KarlstadsenergiApi,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from .const import (
    CONF_AUTH_METHOD,
    CONF_HISTORY_YEARS,
    CONF_PERSONNUMMER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HISTORY_YEARS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_HISTORY_YEARS,
    MAX_UPDATE_INTERVAL,
    MIN_HISTORY_YEARS,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Cross-device BankID QR support.
#
# HA's config-flow markdown strips data: URIs and inline <img>, so the QR PNG
# cannot be embedded directly in a step description. Instead we cache the PNG
# bytes here, keyed by the per-order transaction id, and expose them through a
# tiny HTTP view that the description links to. A user on a desktop can then
# scan the QR with the BankID app on their phone.
QR_URL_BASE = "/api/karlstadsenergi/bankid_qr"
_QR_VIEW_KEY = f"{DOMAIN}_bankid_qr_view"
_QR_STORE: dict[str, bytes] = {}


class KarlstadsenergiBankIDQRView(HomeAssistantView):
    """Serve the BankID QR PNG so it can be scanned cross-device.

    The token is a random per-order transaction id, and scanning the QR only
    lets the scanner *start* a BankID signing (authenticating their own
    identity, not gaining access to anyone else's account), so the view is not
    auth-protected -- an unauthenticated browser fetch from the QR link must
    succeed.
    """

    url = QR_URL_BASE + "/{token}"
    name = "api:karlstadsenergi:bankid_qr"
    requires_auth = False

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return the cached QR PNG for a transaction, or 404."""
        data = _QR_STORE.get(token)
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/png")


def _normalize_personnummer(pnr: str) -> str:
    """Return a Swedish personnummer in 12-digit YYYYMMDDNNNN form.

    BankID signing identifies the person by signature and ignores the typed
    number, but the portal's customer lookup (GetCustomerByPinCode) only
    matches the 12-digit form -- a 10-digit entry signs fine yet returns zero
    accounts. Infer the century from the two-digit year relative to today
    (e.g. in 2026, ``05`` -> ``2005`` and ``27`` -> ``1927``). A wrong guess
    can only fail the lookup as before, never make a 12-digit entry worse.
    """
    pnr = pnr.strip()
    if len(pnr) != 10:
        return pnr
    yy = int(pnr[:2])
    current_yy = datetime.now().year % 100
    century = 2000 if yy <= current_yy else 1900
    return f"{century + yy:04d}{pnr[2:]}"


@callback
def _register_qr_view(hass: HomeAssistant) -> None:
    """Register the QR view once per HA instance."""
    if hass.data.get(_QR_VIEW_KEY):
        return
    hass.http.register_view(KarlstadsenergiBankIDQRView())
    hass.data[_QR_VIEW_KEY] = True


def _auth_method_selector() -> SelectSelector:
    """Build the password/BankID method selector.

    Shared by the initial ``user`` step and the ``reauth_confirm`` step so a
    user can pick (or switch) auth method in either place.
    """
    return SelectSelector(
        SelectSelectorConfig(
            options=[AUTH_PASSWORD, AUTH_BANKID],
            translation_key=CONF_AUTH_METHOD,
        )
    )


_USER_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTH_METHOD, default=AUTH_PASSWORD): _auth_method_selector(),
    }
)


class KarlstadsenergiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Karlstadsenergi."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._personnummer: str = ""
        self._auth_method: str = AUTH_PASSWORD
        self._api: KarlstadsenergiApi | None = None
        self._bankid_init: dict[str, str] = {}
        self._accounts: list[dict[str, Any]] = []
        self._reauth_customer_code: str = ""

    def _reauth_update_and_reload(self, new_data: dict[str, Any]) -> ConfigFlowResult:
        """Finish reauth: update the entry and schedule an explicit reload.

        ``async_update_and_abort()`` does not reload, and the update listener
        only reloads on options changes (and is not registered at all when the
        previous setup failed), so reauth schedules the reload itself.
        """
        reauth_entry = self._get_reauth_entry()
        result = self.async_update_and_abort(reauth_entry, data=new_data)
        self.hass.config_entries.async_schedule_reload(reauth_entry.entry_id)
        return result

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 1: Choose auth method and enter personnummer."""
        if user_input is not None:
            self._auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_PASSWORD)

            if self._auth_method == AUTH_PASSWORD:
                return await self.async_step_password()
            return await self.async_step_bankid_personnummer()

        return self.async_show_form(
            step_id="user",
            data_schema=_USER_STEP_SCHEMA,
        )

    async def async_step_bankid_personnummer(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step for entering personnummer before BankID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._personnummer = user_input.get(CONF_PERSONNUMMER, "").strip()
            if (
                self._personnummer
                and self._personnummer.isdigit()
                and len(self._personnummer) in (10, 12)
            ):
                # The portal's customer lookup only matches the 12-digit form.
                self._personnummer = _normalize_personnummer(self._personnummer)
                return await self.async_step_bankid()
            errors["base"] = "invalid_personnummer"

        return self.async_show_form(
            step_id="bankid_personnummer",
            data_schema=vol.Schema({vol.Required(CONF_PERSONNUMMER): str}),
            errors=errors,
        )

    async def async_step_password(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle password authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            customer_number = user_input["customer_number"]
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(customer_number)
            if self.source != "reauth":
                self._abort_if_unique_id_configured()

            api = KarlstadsenergiApi(
                customer_number,
                AUTH_PASSWORD,
                password,
            )
            try:
                await api.authenticate_password()
                await api.async_get_next_flex_dates()
                cookies = api.get_session_cookies()
            except KarlstadsenergiAccountLockedError:
                errors["base"] = "account_locked"
            except KarlstadsenergiAuthError:
                errors["base"] = "invalid_auth"
            except KarlstadsenergiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during password setup")
                errors["base"] = "unknown"
            finally:
                await api.async_close()

            if not errors:
                new_data = {
                    CONF_PERSONNUMMER: customer_number,
                    CONF_AUTH_METHOD: AUTH_PASSWORD,
                    CONF_PASSWORD: password,
                    "customer_code": customer_number,
                    "session_cookies": cookies,
                }

                if self.source == "reauth":
                    return self._reauth_update_and_reload(new_data)

                return self.async_create_entry(
                    title=f"Karlstadsenergi ({customer_number})",
                    data=new_data,
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required("customer_number", default=self._personnummer): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bankid(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 2 (BankID): Show QR code / deep link and wait for signing."""
        errors: dict[str, str] = {}

        _register_qr_view(self.hass)

        # Ensure an API client exists (first entry, or after a prior cleanup).
        # A Submit that arrives without a live client was acting on a dead
        # order, so void it -- the fresh order created below is what counts.
        if self._api is None:
            self._api = KarlstadsenergiApi(self._personnummer, AUTH_BANKID)
            user_input = None

        if user_input is not None:
            # User clicked Submit -- poll for completion
            try:
                result = None
                for _ in range(15):
                    result = await self._api.bankid_poll(
                        self._bankid_init["order_ref"],
                    )
                    if result["status"] == BANKID_COMPLETE:
                        break
                    if result["status"] not in (
                        BANKID_USER_SIGN,
                        BANKID_OUTSTANDING,
                        5,
                    ):
                        break
                    # Known limitation (B4): This sleep-based polling blocks the
                    # config flow for up to 30 seconds. The recommended HA pattern
                    # is async_show_progress with a background task, but the current
                    # approach works because BankID is a secondary auth method used
                    # by few users. Refactoring to progress steps is deferred.
                    await asyncio.sleep(2)

                _LOGGER.debug(
                    "BankID submit: poll result status=%s",
                    result["status"] if result else None,
                )
                if result and result["status"] == BANKID_COMPLETE:
                    # Get available accounts
                    self._accounts = await self._api.bankid_get_customers(
                        self._personnummer,
                        self._bankid_init["transaction_id"],
                    )
                    _LOGGER.debug("BankID: %d account(s) found", len(self._accounts))
                    if len(self._accounts) == 1:
                        # Only one account -- login directly
                        return await self._do_bankid_login(self._accounts[0])
                    if len(self._accounts) > 1:
                        # Multiple accounts -- show selection
                        return await self.async_step_select_account()
                    # Signed in, but this personnummer has no accounts. Re-signing
                    # won't change that, so send the user back to re-enter it.
                    _LOGGER.warning(
                        "BankID signed successfully but no accounts were "
                        "returned for this personnummer"
                    )
                    await self._cleanup_api()
                    return self.async_show_form(
                        step_id="bankid_personnummer",
                        data_schema=vol.Schema({vol.Required(CONF_PERSONNUMMER): str}),
                        errors={"base": "bankid_failed"},
                    )
                errors["base"] = "bankid_pending"
            except KarlstadsenergiAuthError as err:
                _LOGGER.error("BankID auth failed: %s", err)
                errors["base"] = "bankid_failed"
            except KarlstadsenergiConnectionError as err:
                _LOGGER.error("BankID connection error: %s", err)
                await self._cleanup_api()
                return self._show_user_form({"base": "cannot_connect"})
            except Exception:
                _LOGGER.exception("Unexpected error during BankID setup")
                errors["base"] = "unknown"

        # About to show the form: always start a FRESH order so the QR and deep
        # link shown are never stale. This makes every (re)entry -- first show,
        # a resumed/backed-out-of reauth flow, back-navigation, or a retry after
        # a pending/failed Submit -- hand the user a new, signable code instead
        # of reusing an expired order. Drop the previous order's cached QR first
        # so its token does not leak in _QR_STORE.
        try:
            self._forget_qr()
            self._bankid_init = await self._api.bankid_initiate()
            self._store_qr()
        except KarlstadsenergiConnectionError:
            await self._cleanup_api()
            return self._show_user_form({"base": "cannot_connect"})

        auto_start_token = self._bankid_init.get("auto_start_token", "")
        return self.async_show_form(
            step_id="bankid",
            description_placeholders={
                "personnummer": self._personnummer,
                # Full URL built here, not in strings.json: hassfest rejects
                # literal http(s) URLs in translated strings (TRANSLATIONS check)
                # and requires a placeholder.
                "bankid_url": (
                    "https://app.bankid.com/"
                    f"?autostarttoken={auto_start_token}&redirect=null"
                ),
                # Also provide auto_start_token (the older placeholder name) so a
                # stale cached translation from an earlier version still renders
                # instead of failing with MISSING_VALUE and hiding the whole
                # step (including the QR). Harmless when the string omits it.
                "auto_start_token": auto_start_token,
                "qr_url": f"{QR_URL_BASE}/{self._bankid_init.get('transaction_id', '')}",
            },
            data_schema=vol.Schema({}),
            errors=errors,
        )

    def _store_qr(self) -> None:
        """Cache the current order's QR PNG for the HTTP view to serve."""
        token = self._bankid_init.get("transaction_id", "")
        b64 = self._bankid_init.get("qr_code_base64", "")
        if not token:
            return
        if not b64:
            _QR_STORE.pop(token, None)
            return
        try:
            _QR_STORE[token] = base64.b64decode(b64)
        except (ValueError, TypeError):
            _QR_STORE.pop(token, None)

    def _forget_qr(self) -> None:
        """Drop the cached QR for the current order."""
        token = self._bankid_init.get("transaction_id", "")
        if token:
            _QR_STORE.pop(token, None)

    async def async_step_select_account(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 3: Select which account/contract to use."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_str = user_input.get("account")
            if selected_str is not None:
                try:
                    selected_idx = int(selected_str)
                except (ValueError, TypeError):
                    selected_idx = -1
                if 0 <= selected_idx < len(self._accounts):
                    return await self._do_bankid_login(self._accounts[selected_idx])
            errors["base"] = "unknown"

        options = [
            {"value": str(i), "label": self._account_label(acc)}
            for i, acc in enumerate(self._accounts)
        ]

        return self.async_show_form(
            step_id="select_account",
            data_schema=vol.Schema(
                {
                    vol.Required("account"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    ),
                }
            ),
            errors=errors,
        )

    def _account_label(self, account: dict[str, Any]) -> str:
        name = account.get("full_name", "")
        code = account.get("customer_code", "")
        if name and code:
            return f"{name} ({code})"
        return name or code or "—"

    def _show_user_form(self, errors: dict) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=_USER_STEP_SCHEMA,
            errors=errors,
        )

    @callback
    def async_remove(self) -> None:
        """Clean up API session if flow is aborted.

        Note: HA's base FlowHandler.async_remove() is a @callback (sync),
        not a coroutine. We schedule the async cleanup as a task.
        """
        if self._api:
            self.hass.async_create_task(self._cleanup_api())

    async def _cleanup_api(self) -> None:
        self._forget_qr()
        if self._api:
            await self._api.async_close()
            self._api = None

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Handle re-authentication when session expires."""
        self._personnummer = entry_data.get(CONF_PERSONNUMMER, "")
        self._auth_method = entry_data.get(CONF_AUTH_METHOD, AUTH_PASSWORD)
        self._reauth_customer_code = entry_data.get("customer_code", "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let the user (re)choose the auth method, then run it.

        Reauth is not locked to the entry's stored method: a BankID entry can
        switch to customer number & password (and vice versa). The method is
        pre-selected to whatever the entry currently uses.
        """
        if user_input is not None:
            self._auth_method = user_input.get(CONF_AUTH_METHOD, self._auth_method)

            if self._auth_method == AUTH_PASSWORD:
                # Pre-fill the customer number from the stored customer code
                # instead of the personnummer (which BankID entries store).
                if self._reauth_customer_code:
                    self._personnummer = self._reauth_customer_code
                return await self.async_step_password()

            # BankID needs a valid personnummer. A password entry stores a
            # customer number here, so fall back to asking for the personnummer.
            if self._personnummer.isdigit() and len(self._personnummer) in (10, 12):
                return await self.async_step_bankid()
            return await self.async_step_bankid_personnummer()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTH_METHOD,
                        default=self._auth_method,
                    ): _auth_method_selector(),
                }
            ),
        )

    async def _do_bankid_login(
        self,
        account: dict[str, Any],
    ) -> ConfigFlowResult:
        """Login with selected account and create/update entry."""
        try:
            _LOGGER.debug(
                "BankID login attempt: customer_id set=%s, sub_user=%s",
                bool(account.get("customer_id")),
                bool(account.get("sub_user_id")),
            )
            await self._api.bankid_login(
                self._personnummer,
                account["customer_id"],
                self._bankid_init["transaction_id"],
                account.get("sub_user_id", ""),
            )
            _LOGGER.debug("BankID login OK; verifying data access")

            # Verify data access
            await self._api.async_get_next_flex_dates()
            _LOGGER.debug("BankID data-access verification OK")

            cookies = self._api.get_session_cookies()
            self._forget_qr()
            await self._api.async_close()
            self._api = None

            customer_code = account.get("customer_code", "")
            await self.async_set_unique_id(customer_code)
            if self.source != "reauth":
                self._abort_if_unique_id_configured()

            title = f"Karlstadsenergi ({customer_code})"

            new_data = {
                CONF_PERSONNUMMER: self._personnummer,
                CONF_AUTH_METHOD: AUTH_BANKID,
                "customer_code": customer_code,
                "customer_id": account["customer_id"],
                "sub_user_id": account.get("sub_user_id", ""),
                "session_cookies": cookies,
            }

            if self.source == "reauth":
                return self._reauth_update_and_reload(new_data)

            return self.async_create_entry(title=title, data=new_data)

        except KarlstadsenergiAuthError as err:
            _LOGGER.error("BankID login failed: %s", err)
            await self._cleanup_api()
            return self.async_show_form(
                step_id="bankid_personnummer",
                data_schema=vol.Schema({vol.Required(CONF_PERSONNUMMER): str}),
                errors={"base": "bankid_failed"},
            )
        except Exception:
            _LOGGER.exception("Unexpected error during BankID login")
            await self._cleanup_api()
            return self.async_show_form(
                step_id="bankid_personnummer",
                data_schema=vol.Schema({vol.Required(CONF_PERSONNUMMER): str}),
                errors={"base": "unknown"},
            )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return KarlstadsenergiOptionsFlow()


class KarlstadsenergiOptionsFlow(OptionsFlow):
    """Handle options for Karlstadsenergi."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            interval = int(
                user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            )
            history = int(user_input.get(CONF_HISTORY_YEARS, DEFAULT_HISTORY_YEARS))
            if not (MIN_UPDATE_INTERVAL <= interval <= MAX_UPDATE_INTERVAL):
                errors["base"] = "invalid_interval"
            elif not (MIN_HISTORY_YEARS <= history <= MAX_HISTORY_YEARS):
                errors["base"] = "invalid_history_years"
            else:
                coerced = {
                    **user_input,
                    CONF_UPDATE_INTERVAL: interval,
                    CONF_HISTORY_YEARS: history,
                }
                return self.async_create_entry(title="", data=coerced)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            DEFAULT_UPDATE_INTERVAL,
        )
        current_history = self.config_entry.options.get(
            CONF_HISTORY_YEARS,
            DEFAULT_HISTORY_YEARS,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="hours",
                        )
                    ),
                    vol.Required(
                        CONF_HISTORY_YEARS,
                        default=current_history,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_HISTORY_YEARS,
                            max=MAX_HISTORY_YEARS,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="years",
                        )
                    ),
                }
            ),
            errors=errors,
        )
