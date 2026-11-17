"""Constantes de l'intégration Iléo."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ileo"
MANUFACTURER: Final = "Iléo – Métropole Européenne de Lille"

# Options
CONF_PRICE: Final = "price"
"""Prix fixe de l'eau en €/m³."""
CONF_PRICE_ENTITY: Final = "price_entity"
"""Entité fournissant le prix de l'eau en €/m³ (prioritaire sur le prix fixe)."""

# Les données Iléo arrivent avec ~2 jours de retard : inutile d'interroger souvent.
UPDATE_INTERVAL: Final = timedelta(hours=12)
# Profondeur de l'export demandé au portail (l'espace client propose ~6 mois).
HISTORY_DAYS: Final = 180
