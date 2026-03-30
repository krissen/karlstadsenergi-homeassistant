"""Config flow for Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
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


_USER_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTH_METHOD, default=AUTH_PASSWORD): SelectSelector(
            SelectSelectorConfig(
                options=[AUTH_PASSWORD, AUTH_BANKID],
                translation_key=CONF_AUTH_METHOD,
            )
        ),
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
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
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
        """Step 2 (BankID): Show QR code and wait for signing."""
        errors: dict[str, str] = {}

        # Initiate BankID on first entry
        if self._api is None:
            self._api = KarlstadsenergiApi(
                self._personnummer,
                AUTH_BANKID,
            )
            try:
                # QR code (qr_code_base64) is available from the API but cannot be
                # displayed in HA's config flow UI -- the frontend sanitizes data URIs
                # and <img> tags in description markdown. Users authenticate via the
                # bankid:// deep link shown in the description instead.
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
                    # Known limitation (B4): This sleep-based polling blocks the
                    # config flow for up to 30 seconds. The recommended HA pattern
                    # is async_show_progress with a background task, but the current
                    # approach works because BankID is a secondary auth method used
                    # by few users. Refactoring to progress steps is deferred.
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

        return self.async_show_form(
            step_id="bankid",
            description_placeholders={
                "personnummer": self._personnummer,
                "auto_start_token": auto_start_token,
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

    async def async_remove(self) -> None:
        """Clean up API session if flow is aborted."""
        await self._cleanup_api()

    async def _cleanup_api(self) -> None:
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
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Route reauth to the correct method-specific step."""
        if self._auth_method == AUTH_PASSWORD:
            return await self.async_step_reauth_confirm_password(user_input)
        return await self.async_step_reauth_confirm_bankid(user_input)

    async def async_step_reauth_confirm_password(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Reauth confirmation for password users."""
        if user_input is not None:
            return await self.async_step_password()
        return self.async_show_form(
            step_id="reauth_confirm_password",
            data_schema=vol.Schema({}),
        )

    async def async_step_reauth_confirm_bankid(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Reauth confirmation for BankID users."""
        if user_input is not None:
            return await self.async_step_bankid()
        return self.async_show_form(
            step_id="reauth_confirm_bankid",
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
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data=new_data,
                )

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
            interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            if not (MIN_UPDATE_INTERVAL <= interval <= MAX_UPDATE_INTERVAL):
                errors["base"] = "invalid_interval"
            else:
                return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
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
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="hours",
                        )
                    ),
                }
            ),
            errors=errors,
        )
