"""UniFi Protect Platform."""

import asyncio
import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import voluptuous as vol
from aiohttp import CookieJar
from aiohttp.client_exceptions import ServerDisconnectedError
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType, HomeAssistantType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyunifiprotect import UpvServer, NotAuthorized, NvrError

from .const import (
    CONF_SNAPSHOT_DIRECT,
    DEFAULT_BRAND,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    UNIFI_PROTECT_PLATFORMS,
    CONTROLLER_CONFIG_SCHEMA)

SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [CONTROLLER_CONFIG_SCHEMA]
        )
    },
    extra=vol.ALLOW_EXTRA
)


async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    """Set up the UniFi Protect components."""
    conf = config.get(DOMAIN, None)
    if not conf:
        return True

    configured_controllers = {
        entry.data.get(CONF_HOST) for entry in hass.config_entries.async_entries(DOMAIN)
    }

    hass.data.setdefault(DOMAIN, {})

    for controller_config in conf:
        if controller_config[CONF_HOST] not in configured_controllers:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_IMPORT},
                    data=controller_config
                )
            )

    return True


async def async_setup_entry(hass: HomeAssistantType, entry: ConfigEntry) -> bool:
    """Set up the UniFi Protect config entries."""

    if not entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_SCAN_INTERVAL: entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
                CONF_SNAPSHOT_DIRECT: entry.data.get(CONF_SNAPSHOT_DIRECT, False),
            },
        )

    session = async_create_clientsession(hass, cookie_jar=CookieJar(unsafe=True))
    protect_server = UpvServer(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = protect_server
    _LOGGER.debug("Connect to UniFi Protect")

    events_update_interval = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=protect_server.update,
        update_interval=timedelta(seconds=events_update_interval),
    )

    try:
        nvr_info = await protect_server.server_information()
    except NotAuthorized:
        _LOGGER.error(
            "Could not Authorize against UniFi Protect. Please reinstall the Integration."
        )
        return False
    except (NvrError, ServerDisconnectedError):
        raise ConfigEntryNotReady

    await coordinator.async_refresh()
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "upv": protect_server,
        "snapshot_direct": entry.options.get(CONF_SNAPSHOT_DIRECT, False),
    }

    await _async_get_or_create_nvr_device_in_registry(hass, entry, nvr_info)

    for platform in UNIFI_PROTECT_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    if not entry.update_listeners:
        entry.add_update_listener(async_update_options)

    return True


async def _async_get_or_create_nvr_device_in_registry(
        hass: HomeAssistantType, entry: ConfigEntry, nvr
) -> None:
    device_registry = await dr.async_get_registry(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, nvr["server_id"])},
        identifiers={(DOMAIN, nvr["server_id"])},
        manufacturer=DEFAULT_BRAND,
        name=entry.data[CONF_ID],
        model=nvr["server_model"],
        sw_version=nvr["server_version"],
    )


async def async_update_options(hass: HomeAssistantType, entry: ConfigEntry):
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistantType, entry: ConfigEntry) -> bool:
    """Unload UniFi Protect config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in UNIFI_PROTECT_PLATFORMS
            ]
        )
    )

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
