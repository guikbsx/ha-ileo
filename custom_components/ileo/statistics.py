"""Statistiques externes datées au jour réel de consommation.

Les données Iléo arrivent avec environ deux jours de retard : un capteur classique
attribuerait la consommation au jour de la récupération. On injecte donc des
statistiques externes (`ileo:…`), une ligne par jour, horodatée à 00:00 (heure
locale) du jour consommé, utilisables dans le tableau de bord Énergie.

Règles de calcul de la `sum` :
- c'est le cumul des écarts d'index d'un jour sur l'autre, jamais l'index brut
  (pas de pic au premier import) ;
- un index qui recule (remplacement de compteur, correction) compte pour 0 et
  sert de nouvelle base ;
- le tout premier jour, sans index précédent, vaut la consommation fournie par
  l'export si elle existe, sinon 0 ;
- l'import est incrémental : on repart de la dernière statistique enregistrée et
  on n'ajoute que les jours postérieurs, donc pas de doublon à la réinjection.
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


@dataclass(frozen=True, slots=True)
class DailyDelta:
    """Consommation d'un jour, en litres, déduite des index."""

    day: date
    index: float | None
    delta: float


@dataclass(frozen=True, slots=True)
class LastStatistic:
    """Dernière ligne enregistrée pour une statistique."""

    day: date
    sum: float
    state: float | None


def compute_daily_deltas(
    readings: Iterable[IleoReading], previous_index: float | None = None
) -> list[DailyDelta]:
    """Calcule la consommation de chaque jour (litres, toujours >= 0).

    `previous_index` est l'index connu avant le premier relevé (par exemple le
    dernier index déjà importé), utilisé seulement pour le premier relevé.
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
    """Construit les lignes à importer après `last` (exclu).

    `factor` convertit des litres vers l'unité de la statistique (1 pour des
    litres, prix/1000 pour un coût en euros à partir d'un prix au m³).
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


def statistic_ids(account: str) -> tuple[str, str]:
    """Identifiants (consommation, coût) des statistiques d'un compte."""
    slug = slugify(account)
    return f"{DOMAIN}:{slug}_consommation", f"{DOMAIN}:{slug}_cout"


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
    account: str,
    name: str,
    readings: Sequence[IleoReading],
    price_per_m3: float | None = None,
) -> list[DailyDelta]:
    """Injecte les nouveaux jours dans les statistiques de consommation (et de coût).

    Retourne les consommations journalières calculées.
    """
    consumption_id, cost_id = statistic_ids(account)
    tz = dt_util.get_default_time_zone()

    last = await _async_last_statistic(hass, consumption_id)
    deltas = compute_daily_deltas(readings, last.state if last else None)

    if rows := build_statistics(deltas, tz=tz, last=last):
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{name} – consommation",
            source=DOMAIN,
            statistic_id=consumption_id,
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.LITERS,
        )
        _LOGGER.debug("Import de %s jours dans %s", len(rows), consumption_id)
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
                name=f"{name} – coût",
                source=DOMAIN,
                statistic_id=cost_id,
                unit_class=None,
                unit_of_measurement=CURRENCY,
            )
            _LOGGER.debug("Import de %s jours dans %s", len(rows), cost_id)
            async_add_external_statistics(hass, metadata, rows)

    return deltas
