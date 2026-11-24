"""Iléo integration: water consumption of the Métropole Européenne de Lille."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import IleoClient
from .const import CONF_CONTRACT, DOMAIN
from .coordinator import IleoConfigEntry, IleoCoordinator, contract_issue_id

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


async def async_remove_entry(hass: HomeAssistant, entry: IleoConfigEntry) -> None:
    """Clean up after a removed entry: its repair issue would have no owner."""
    ir.async_delete_issue(hass, DOMAIN, contract_issue_id(entry.data[CONF_CONTRACT]))
