"""Data update coordinator of the Iléo integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import IleoClient
from .const import (
    CONF_CONTRACT,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    DOMAIN,
    HISTORY_DAYS,
    UPDATE_INTERVAL,
)
from .models import IleoAuthError, IleoConnectionError, IleoError, IleoReading
from .statistics import DailyDelta, async_import_statistics

_LOGGER = logging.getLogger(__name__)

type IleoConfigEntry = ConfigEntry[IleoCoordinator]


@dataclass(slots=True)
class IleoData:
    """Data exposed to the sensors."""

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


def _valid_price(value: Any) -> float | None:
    """Price in €/m³: a finite positive number, else None."""
    try:
        price = float(value)
    except TypeError, ValueError:
        return None
    return price if math.isfinite(price) and price >= 0 else None


class IleoCoordinator(DataUpdateCoordinator[IleoData]):
    """Fetch the Iléo export every 12 hours and feed the statistics."""

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
        self.contract: str = entry.data[CONF_CONTRACT]

    def price_per_m3(self) -> float | None:
        """Water price in €/m³: chosen entity, else fixed value, else none."""
        options = self.config_entry.options
        if entity_id := options.get(CONF_PRICE_ENTITY):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                _LOGGER.warning("Water price unavailable (%s)", entity_id)
                return None
            price = _valid_price(state.state)
            if price is None:
                _LOGGER.warning("Invalid water price (%s = %s)", entity_id, state.state)
            return price
        return _valid_price(options.get(CONF_PRICE))

    async def _async_update_data(self) -> IleoData:
        today = dt_util.now().date()
        try:
            readings = await self.client.async_get_readings(
                today - timedelta(days=HISTORY_DAYS), today
            )
        except IleoAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except IleoError as err:
            _LOGGER.debug("Fetching the Iléo export failed: %s", err)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key=(
                    "cannot_connect"
                    if isinstance(err, IleoConnectionError)
                    else "unexpected_response"
                ),
            ) from err

        # A day dated in the future would block the incremental import until then.
        readings = [reading for reading in readings if reading.day <= today]
        if not readings:
            _LOGGER.info("No consumption data in the Iléo export")
            return IleoData()

        deltas = await async_import_statistics(
            self.hass,
            contract=self.contract,
            readings=readings,
            price_per_m3=self.price_per_m3(),
        )
        return IleoData(readings=readings, deltas=deltas)
