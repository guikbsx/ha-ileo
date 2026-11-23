"""Constants of the Iléo integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ileo"
MANUFACTURER: Final = "Iléo – Métropole Européenne de Lille"

# Config entry data
CONF_CONTRACT: Final = "contract"
"""Number of the water contract followed by the config entry."""

# Options
CONF_PRICE: Final = "price"
"""Fixed water price, in €/m³."""
CONF_PRICE_ENTITY: Final = "price_entity"
"""Entity providing the water price in €/m³ (takes precedence over the fixed price)."""

# Iléo data is about two days late: polling more often would be pointless.
UPDATE_INTERVAL: Final = timedelta(hours=12)
# Depth of the export requested from the portal (it offers about 6 months).
HISTORY_DAYS: Final = 180
