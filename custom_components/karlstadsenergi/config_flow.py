"""Config flow for Karlstadsenergi integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import (
    KarlstadsenergiApi,
    KarlstadsenergiAuthError,
    KarlstadsenergiConnectionError,
)
from .const import (
    CONF_CUSTOMER_NUMBER,
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            customer_number = user_input[CONF_CUSTOMER_NUMBER]
            password = user_input[CONF_PASSWORD]

            # Check for duplicate
            await self.async_set_unique_id(customer_number)
            self._abort_if_unique_id_configured()

            # Validate credentials
            api = KarlstadsenergiApi(customer_number, password)
            try:
                await api.authenticate()
                await api.async_get_flex_services()
            except KarlstadsenergiAuthError:
                errors["base"] = "invalid_auth"
            except KarlstadsenergiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            finally:
                await api.async_close()

            if not errors:
                return self.async_create_entry(
                    title=f"Karlstadsenergi ({customer_number})",
                    data={
                        CONF_CUSTOMER_NUMBER: customer_number,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOMER_NUMBER): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
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
