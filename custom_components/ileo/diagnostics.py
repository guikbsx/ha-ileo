"""Diagnostics of the Iléo integration.

The file downloaded from the UI is meant to be attached to a bug report: it
holds no credentials, no email address, no contract number and no water volume.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_CONTRACT
from .coordinator import IleoConfigEntry, IleoCoordinator

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_CONTRACT, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IleoConfigEntry
) -> dict[str, Any]:
    """Return the state of the config entry, with personal data redacted."""
    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "state": entry.state.value,
        "coordinator": None,
    }
    # Diagnostics matter most when the setup failed, in which case the entry
    # has no coordinator.
    coordinator: IleoCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is not None and coordinator.data is not None:
        readings = coordinator.data.readings
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "readings": len(readings),
            "first_day": readings[0].day.isoformat() if readings else None,
            "last_day": readings[-1].day.isoformat() if readings else None,
            "with_index": sum(reading.index is not None for reading in readings),
        }
    return diagnostics
