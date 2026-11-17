"""Coordinateur de mise à jour des données Iléo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import IleoClient
from .const import CONF_PRICE, CONF_PRICE_ENTITY, DOMAIN, HISTORY_DAYS, UPDATE_INTERVAL
from .models import IleoAuthError, IleoError, IleoReading
from .statistics import DailyDelta, async_import_statistics

_LOGGER = logging.getLogger(__name__)

type IleoConfigEntry = ConfigEntry[IleoCoordinator]


@dataclass(slots=True)
class IleoData:
    """Données exposées aux capteurs."""

    readings: list[IleoReading] = field(default_factory=list)
    deltas: list[DailyDelta] = field(default_factory=list)

    @property
    def latest(self) -> IleoReading | None:
        return self.readings[-1] if self.readings else None

    @property
    def latest_index(self) -> float | None:
        for reading in reversed(self.readings):
            if reading.index is not None:
                return reading.index
        return None

    @property
    def last_day_consumption(self) -> float | None:
        return self.deltas[-1].delta if self.deltas else None


class IleoCoordinator(DataUpdateCoordinator[IleoData]):
    """Récupère l'export Iléo toutes les 12 h et alimente les statistiques."""

    config_entry: IleoConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: IleoConfigEntry, client: IleoClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    @property
    def account(self) -> str:
        return self.config_entry.unique_id or self.config_entry.entry_id

    def price_per_m3(self) -> float | None:
        """Prix de l'eau en €/m³ : entité choisie, sinon valeur fixe, sinon aucun."""
        options = self.config_entry.options
        if entity_id := options.get(CONF_PRICE_ENTITY):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                _LOGGER.warning("Prix de l'eau indisponible (%s)", entity_id)
                return None
            try:
                return float(state.state)
            except ValueError:
                _LOGGER.warning(
                    "Prix de l'eau non numérique (%s = %s)", entity_id, state.state
                )
                return None
        if (price := options.get(CONF_PRICE)) is not None:
            return float(price)
        return None

    async def _async_update_data(self) -> IleoData:
        today = dt_util.now().date()
        try:
            readings = await self.client.async_get_readings(
                today - timedelta(days=HISTORY_DAYS), today
            )
        except IleoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except IleoError as err:
            raise UpdateFailed(str(err)) from err

        if not readings:
            _LOGGER.info("Aucune donnée de consommation dans l'export Iléo")
            return IleoData()

        deltas = await async_import_statistics(
            self.hass,
            account=self.account,
            name=self.config_entry.title,
            readings=readings,
            price_per_m3=self.price_per_m3(),
        )
        return IleoData(readings=readings, deltas=deltas)
