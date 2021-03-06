""" Config Flow to configure UniFi Protect Integration. """
import logging

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant import config_entries
from homeassistant.const import (
    CONF_ID,
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import HomeAssistantType
from pyunifiprotect import UpvServer, NotAuthorized, NvrError

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    CONF_SNAPSHOT_DIRECT,
    CONF_IR_ON,
    CONF_IR_OFF,
    CONTROLLER_CONFIG_SCHEMA)

_LOGGER = logging.getLogger(__name__)


async def _get_controller_id(hass: HomeAssistantType, controller_config) -> str:
    session = async_create_clientsession(
        hass, cookie_jar=CookieJar(unsafe=True)
    )

    unifi_protect = UpvServer(
        session,
        controller_config[CONF_HOST],
        controller_config[CONF_PORT],
        controller_config[CONF_USERNAME],
        controller_config[CONF_PASSWORD],
    )

    return await unifi_protect.unique_id()


class UniFiProtectFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a UniFi Protect config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        if user_input is None:
            return await self._show_setup_form(user_input)

        errors = {}

        try:
            unique_id = await _get_controller_id(self.hass, user_input)
        except NotAuthorized:
            errors["base"] = "connection_error"
            return await self._show_setup_form(errors)
        except NvrError:
            errors["base"] = "nvr_error"
            return await self._show_setup_form(errors)

        entries = self._async_current_entries()
        for entry in entries:
            if entry.data[CONF_ID] == unique_id:
                return self.async_abort(reason="server_exists")

        return self.async_create_entry(
            title=unique_id,
            data={
                CONF_ID: unique_id,
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_USERNAME: user_input.get(CONF_USERNAME),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD),
                CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL),
                CONF_SNAPSHOT_DIRECT: user_input.get(CONF_SNAPSHOT_DIRECT),
                CONF_IR_ON: user_input.get(CONF_IR_ON),
                CONF_IR_OFF: user_input.get(CONF_IR_OFF),
            },
        )

    async def _show_setup_form(self, errors=None):
        """Show the setup form to the user."""
        return self.async_show_form(
            step_id="user",
            data_schema=CONTROLLER_CONFIG_SCHEMA,
            errors=errors or {},
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            try:
                controller_id = await _get_controller_id(self.hass, user_input)
                if controller_id:
                    user_input[CONF_ID] = controller_id
            except NotAuthorized:
                return self.async_abort(reason="connection_error")
            except NvrError:
                return self.async_abort(reason="nvr_error")

            if user_input.get(CONF_ID):
                return self.async_create_entry(title=controller_id, data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SNAPSHOT_DIRECT,
                        default=self.config_entry.options.get(
                            CONF_SNAPSHOT_DIRECT, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=2, max=20)),
                }
            ),
        )
