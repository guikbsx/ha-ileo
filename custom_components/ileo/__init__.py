"""Iléo integration: water consumption of the Métropole Européenne de Lille."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import IleoClient
from .const import CONF_CONTRACT
from .coordinator import IleoConfigEntry, IleoCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: IleoConfigEntry) -> bool:
    """Set up an Iléo config entry."""
    # Dedicated session: the sign-in cookies are not shared with anything else.
    session = async_create_clientsession(hass, auto_cleanup=False)
    entry.async_on_unload(session.detach)
    client = IleoClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        contract=entry.data[CONF_CONTRACT],
    )
    coordinator = IleoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IleoConfigEntry) -> bool:
    """Unload an Iléo config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
