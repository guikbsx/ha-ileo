"""External statistics dated on the day the water was actually consumed.

Iléo data is about two days late: a regular sensor would credit the consumption
to the day it was fetched. So external statistics (`ileo:…`) are imported
instead, one row per day, timestamped at 00:00 (local time) of the consumed
day. They can be used in the Energy dashboard.

How the `sum` is computed:
- it is the running total of index differences from one day to the next, never
  the raw index (no spike on the first import);
- an index going backwards (meter replaced, correction) counts for 0 and
  becomes the new baseline;
- the very first day, with no previous index, is worth the consumption given by
  the export if any, else 0;
- the import is incremental: it resumes after the last recorded statistic and
  only adds later days, so importing the same export twice creates no duplicate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util, slugify
from homeassistant.util.unit_conversion import VolumeConverter

from .const import DOMAIN
from .models import IleoReading

_LOGGER = logging.getLogger(__name__)

CURRENCY = "EUR"

# Statistic names are stored once in the database: they follow the language of
# the instance at the time of the first import.
_NAMES = {
    "fr": ("Iléo {contract} – consommation d'eau", "Iléo {contract} – coût de l'eau"),
}
_DEFAULT_NAMES = ("Iléo {contract} water consumption", "Iléo {contract} water cost")


@dataclass(frozen=True, slots=True)
class DailyDelta:
    """Consumption of one day, in litres, derived from the indexes."""

    day: date
    index: float | None
    delta: float


@dataclass(frozen=True, slots=True)
class LastStatistic:
    """Last recorded row of a statistic."""

    day: date
    sum: float
    state: float | None


def compute_daily_deltas(
    readings: Iterable[IleoReading], previous_index: float | None = None
) -> list[DailyDelta]:
    """Compute the consumption of each day (litres, always >= 0).

    `previous_index` is the index known before the first reading (for instance
    the last imported index); it is only used for the first reading.
    """
    deltas: list[DailyDelta] = []
    base = previous_index
    for reading in sorted(readings, key=lambda r: r.day):
        if reading.index is not None and base is not None:
            delta = max(reading.index - base, 0.0)
        elif reading.consumption is not None and reading.consumption >= 0:
            delta = reading.consumption
        else:
            delta = 0.0
        if reading.index is not None:
            base = reading.index
        deltas.append(DailyDelta(reading.day, reading.index, round(delta, 3)))
    return deltas


def build_statistics(
    deltas: Sequence[DailyDelta],
    *,
    tz: tzinfo,
    last: LastStatistic | None = None,
    factor: float = 1.0,
    include_state: bool = True,
) -> list[StatisticData]:
    """Build the rows to import after `last` (excluded).

    `factor` converts litres to the unit of the statistic (1 for litres,
    price/1000 for a cost in euros from a price per m³).
    """
    total = last.sum if last else 0.0
    rows: list[StatisticData] = []
    for item in deltas:
        if last is not None and item.day <= last.day:
            continue
        total += item.delta * factor
        row = StatisticData(
            start=datetime.combine(item.day, time.min, tzinfo=tz),
            sum=round(total, 6),
        )
        if include_state and item.index is not None:
            row["state"] = item.index
        rows.append(row)
    return rows


def statistic_ids(contract: str) -> tuple[str, str]:
    """Return the (consumption, cost) statistic ids of a contract."""
    slug = slugify(contract)
    return f"{DOMAIN}:{slug}_water_consumption", f"{DOMAIN}:{slug}_water_cost"


def statistic_names(contract: str, language: str) -> tuple[str, str]:
    """Return the (consumption, cost) statistic names of a contract."""
    names = _NAMES.get(language, _DEFAULT_NAMES)
    return names[0].format(contract=contract), names[1].format(contract=contract)


async def _async_last_statistic(
    hass: HomeAssistant, statistic_id: str
) -> LastStatistic | None:
    result = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, False, {"state", "sum"}
    )
    if not (rows := result.get(statistic_id)):
        return None
    row = rows[0]
    start = dt_util.as_local(dt_util.utc_from_timestamp(row["start"]))
    return LastStatistic(
        day=start.date(), sum=row.get("sum") or 0.0, state=row.get("state")
    )


async def async_import_statistics(
    hass: HomeAssistant,
    *,
    contract: str,
    readings: Sequence[IleoReading],
    price_per_m3: float | None = None,
) -> list[DailyDelta]:
    """Import the new days into the consumption (and cost) statistics.

    Returns the computed daily consumptions.
    """
    consumption_id, cost_id = statistic_ids(contract)
    consumption_name, cost_name = statistic_names(contract, hass.config.language)
    tz = dt_util.get_default_time_zone()

    last = await _async_last_statistic(hass, consumption_id)
    deltas = compute_daily_deltas(readings, last.state if last else None)

    if rows := build_statistics(deltas, tz=tz, last=last):
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=consumption_name,
            source=DOMAIN,
            statistic_id=consumption_id,
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.LITERS,
        )
        _LOGGER.debug("Importing %s day(s) into %s", len(rows), consumption_id)
        async_add_external_statistics(hass, metadata, rows)

    if price_per_m3 is not None:
        last_cost = await _async_last_statistic(hass, cost_id)
        if rows := build_statistics(
            deltas,
            tz=tz,
            last=last_cost,
            factor=price_per_m3 / 1000,
            include_state=False,
        ):
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=cost_name,
                source=DOMAIN,
                statistic_id=cost_id,
                unit_class=None,
                unit_of_measurement=CURRENCY,
            )
            _LOGGER.debug("Importing %s day(s) into %s", len(rows), cost_id)
            async_add_external_statistics(hass, metadata, rows)

    return deltas
