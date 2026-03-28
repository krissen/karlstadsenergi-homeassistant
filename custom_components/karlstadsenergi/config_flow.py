"""Config flow for Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback

from .api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
    BANKID_COMPLETE,
    KarlstadsenergiApi,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from .const import (
    CONF_AUTH_METHOD,
    CONF_PERSONNUMMER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class KarlstadsenergiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Karlstadsenergi."""

    VERSION = 1

    def __init__(self) -> None:
        self._personnummer: str = ""
        self._auth_method: str = AUTH_BANKID
        self._api: KarlstadsenergiApi | None = None
        self._bankid_init: dict[str, str] = {}
        self._accounts: list[dict[str, Any]] = []

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 1: Choose auth method and enter personnummer."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_BANKID)

            if self._auth_method == AUTH_PASSWORD:
                return await self.async_step_password()
            return await self.async_step_bankid_personnummer()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=AUTH_BANKID): vol.In(
                        {
                            AUTH_BANKID: "Mobilt BankID",
                            AUTH_PASSWORD: "Kundnummer & lösenord",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_bankid_personnummer(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step for entering personnummer before BankID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._personnummer = user_input.get(CONF_PERSONNUMMER, "")
            if self._personnummer:
                await self.async_set_unique_id(self._personnummer)
                self._abort_if_unique_id_configured()
                return await self.async_step_bankid()
            errors["base"] = "invalid_auth"

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
            api = KarlstadsenergiApi(
                customer_number,
                AUTH_PASSWORD,
                password,
            )
            try:
                await api.authenticate_password()
                await api.async_get_next_flex_dates()
                cookies = api.get_session_cookies()
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
                    "session_cookies": cookies,
                }

                # Check if this is a reauth
                reauth_entry = self.hass.config_entries.async_get_entry(
                    self.context.get("entry_id", ""),
                )
                if reauth_entry:
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data=new_data,
                    )

                return self.async_create_entry(
                    title=f"Karlstadsenergi ({customer_number})",
                    data=new_data,
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required("customer_number"): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bankid(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 2 (BankID): Show QR code and wait for signing."""
        errors: dict[str, str] = {}

        # Initiate BankID on first entry
        if self._api is None:
            self._api = KarlstadsenergiApi(
                self._personnummer,
                AUTH_BANKID,
            )
            try:
                self._bankid_init = await self._api.bankid_initiate()
            except KarlstadsenergiConnectionError:
                errors["base"] = "cannot_connect"
                await self._api.async_close()
                self._api = None
                return self._show_user_form(errors)

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
                    if result["status"] not in (1, 2, 5):
                        break
                    await asyncio.sleep(2)

                if result and result["status"] == BANKID_COMPLETE:
                    # Get available accounts
                    self._accounts = await self._api.bankid_get_customers(
                        self._personnummer,
                        self._bankid_init["transaction_id"],
                    )
                    if len(self._accounts) == 1:
                        # Only one account -- login directly
                        return await self._do_bankid_login(self._accounts[0])
                    elif len(self._accounts) > 1:
                        # Multiple accounts -- show selection
                        return await self.async_step_select_account()
                    else:
                        errors["base"] = "bankid_failed"
                else:
                    errors["base"] = "bankid_pending"
                    # Re-initiate for next attempt
                    try:
                        self._bankid_init = await self._api.bankid_initiate()
                    except KarlstadsenergiConnectionError:
                        errors["base"] = "cannot_connect"
                        await self._cleanup_api()
            except KarlstadsenergiAuthError as err:
                _LOGGER.error("BankID auth failed: %s", err)
                errors["base"] = "bankid_failed"
                await self._cleanup_api()
            except KarlstadsenergiConnectionError as err:
                _LOGGER.error("BankID connection error: %s", err)
                errors["base"] = "cannot_connect"
                await self._cleanup_api()
            except Exception:
                _LOGGER.exception("Unexpected error during BankID setup")
                errors["base"] = "unknown"
                await self._cleanup_api()

        auto_start_token = self._bankid_init.get("auto_start_token", "")
        qr_base64 = self._bankid_init.get("qr_code_base64", "")

        return self.async_show_form(
            step_id="bankid",
            description_placeholders={
                "personnummer": self._personnummer,
                "auto_start_token": auto_start_token,
                "qr_code": qr_base64,
            },
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_select_account(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 3: Select which account/contract to use."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get("account")
            # Find selected account
            for account in self._accounts:
                label = self._account_label(account)
                if label == selected:
                    return await self._do_bankid_login(account)
            errors["base"] = "unknown"

        # Build selection options
        options = {}
        for account in self._accounts:
            label = self._account_label(account)
            options[label] = label

        return self.async_show_form(
            step_id="select_account",
            data_schema=vol.Schema(
                {
                    vol.Required("account"): vol.In(options),
                }
            ),
            errors=errors,
        )

    def _account_label(self, account: dict[str, Any]) -> str:
        name = account.get("full_name", "")
        code = account.get("customer_code", "")
        if name and code:
            return f"{name} ({code})"
        return name or code or "Unknown"

    def _show_user_form(self, errors: dict) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=AUTH_BANKID): vol.In(
                        {
                            AUTH_BANKID: "Mobilt BankID",
                            AUTH_PASSWORD: "Kundnummer & lösenord",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def _cleanup_api(self) -> None:
        if self._api:
            await self._api.async_close()
            self._api = None

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle re-authentication when session expires."""
        self._personnummer = entry_data.get(CONF_PERSONNUMMER, "")
        self._auth_method = entry_data.get(CONF_AUTH_METHOD, AUTH_BANKID)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show reauth confirmation and route to the correct auth flow."""
        if user_input is not None:
            if self._auth_method == AUTH_PASSWORD:
                return await self.async_step_password()
            return await self.async_step_bankid()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                "personnummer": self._personnummer,
            },
            data_schema=vol.Schema({}),
        )

    async def _do_bankid_login(
        self,
        account: dict[str, Any],
    ) -> ConfigFlowResult:
        """Login with selected account and create/update entry."""
        try:
            await self._api.bankid_login(
                self._personnummer,
                account["customer_id"],
                self._bankid_init["transaction_id"],
                account.get("sub_user_id", ""),
            )

            # Verify data access
            await self._api.async_get_next_flex_dates()

            cookies = self._api.get_session_cookies()
            await self._api.async_close()
            self._api = None

            customer_code = account.get("customer_code", "")
            full_name = account.get("full_name", "")
            title = (
                f"Karlstadsenergi {full_name} ({customer_code})"
                if full_name
                else f"Karlstadsenergi ({customer_code})"
            )

            new_data = {
                CONF_PERSONNUMMER: self._personnummer,
                CONF_AUTH_METHOD: AUTH_BANKID,
                "customer_code": customer_code,
                "customer_id": account["customer_id"],
                "sub_user_id": account.get("sub_user_id", ""),
                "session_cookies": cookies,
            }

            # Check if this is a reauth
            reauth_entry = self.hass.config_entries.async_get_entry(
                self.context.get("entry_id", ""),
            )
            if reauth_entry:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data=new_data,
                )

            return self.async_create_entry(title=title, data=new_data)

        except KarlstadsenergiAuthError as err:
            _LOGGER.error("BankID login failed: %s", err)
            await self._cleanup_api()
            return self.async_abort(reason="bankid_failed")
        except Exception:
            _LOGGER.exception("Unexpected error during BankID login")
            await self._cleanup_api()
            return self.async_abort(reason="unknown")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return KarlstadsenergiOptionsFlow(config_entry)


class KarlstadsenergiOptionsFlow(OptionsFlow):
    """Handle options for Karlstadsenergi."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            DEFAULT_UPDATE_INTERVAL,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                        ),
                    ),
                }
            ),
        )
