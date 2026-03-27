"""Config flow for Karlstadsenergi integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import (
    AUTH_BANKID,
    AUTH_PASSWORD,
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
        """Initialize config flow."""
        self._personnummer: str = ""
        self._auth_method: str = AUTH_BANKID
        self._api: KarlstadsenergiApi | None = None
        self._bankid_init: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step: choose auth method."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._personnummer = user_input[CONF_PERSONNUMMER]
            self._auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_BANKID)

            await self.async_set_unique_id(self._personnummer)
            self._abort_if_unique_id_configured()

            if self._auth_method == AUTH_PASSWORD:
                return await self.async_step_password()
            return await self.async_step_bankid()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PERSONNUMMER): str,
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

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle password authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            api = KarlstadsenergiApi(
                self._personnummer, AUTH_PASSWORD, password,
            )
            try:
                await api.authenticate_password()
                await api.async_get_flex_services()
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
                return self.async_create_entry(
                    title=f"Karlstadsenergi ({self._personnummer})",
                    data={
                        CONF_PERSONNUMMER: self._personnummer,
                        CONF_AUTH_METHOD: AUTH_PASSWORD,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_bankid(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle BankID authentication: initiate and show link."""
        errors: dict[str, str] = {}

        if self._api is None:
            self._api = KarlstadsenergiApi(
                self._personnummer, AUTH_BANKID,
            )
            try:
                self._bankid_init = await self._api.bankid_initiate()
            except KarlstadsenergiConnectionError:
                errors["base"] = "cannot_connect"
                await self._api.async_close()
                self._api = None
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_PERSONNUMMER): str,
                            vol.Required(
                                CONF_AUTH_METHOD, default=AUTH_BANKID,
                            ): vol.In(
                                {
                                    AUTH_BANKID: "Mobilt BankID",
                                    AUTH_PASSWORD: "Kundnummer & lösenord",
                                }
                            ),
                        }
                    ),
                    errors=errors,
                )

        if user_input is not None:
            # User clicked Submit - poll for completion
            try:
                # Poll a few times to give user time
                result = None
                for _ in range(15):
                    result = await self._api.bankid_poll(
                        self._bankid_init["order_ref"],
                    )
                    if result["status"] == 0:  # COMPLETE
                        break
                    if result["status"] not in (1, 2, 5):
                        break
                    await asyncio.sleep(2)

                if result and result["status"] == 0:
                    # Extract data for login
                    collect = result["data"].get("CollectResponseType", {})
                    validation = collect.get("validationInfoField", {})
                    data_field = ""
                    if validation:
                        attrs = validation.get("attributesField", {})
                        attr_list = attrs.get("attributeField", [])
                        for attr in attr_list:
                            if attr.get("nameField") == "userData":
                                data_field = attr.get("valueField", "")
                                break

                    await self._api.bankid_complete(
                        self._bankid_init["transaction_id"],
                        self._personnummer,
                        data_field,
                    )

                    # Verify we can fetch data
                    await self._api.async_get_flex_services()
                    await self._api.async_close()
                    self._api = None

                    return self.async_create_entry(
                        title=f"Karlstadsenergi ({self._personnummer})",
                        data={
                            CONF_PERSONNUMMER: self._personnummer,
                            CONF_AUTH_METHOD: AUTH_BANKID,
                        },
                    )
                else:
                    errors["base"] = "bankid_pending"
                    # Re-initiate for next attempt
                    try:
                        self._bankid_init = (
                            await self._api.bankid_initiate()
                        )
                    except KarlstadsenergiConnectionError:
                        errors["base"] = "cannot_connect"
                        await self._api.async_close()
                        self._api = None
            except KarlstadsenergiAuthError:
                errors["base"] = "bankid_failed"
                await self._api.async_close()
                self._api = None
            except KarlstadsenergiConnectionError:
                errors["base"] = "cannot_connect"
                await self._api.async_close()
                self._api = None
            except Exception:
                _LOGGER.exception("Unexpected error during BankID setup")
                errors["base"] = "unknown"
                await self._api.async_close()
                self._api = None

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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow."""
        return KarlstadsenergiOptionsFlow(config_entry)


class KarlstadsenergiOptionsFlow(OptionsFlow):
    """Handle options for Karlstadsenergi."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL,
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
