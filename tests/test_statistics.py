"""Tests du calcul et de l'import des statistiques."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.statistics import (
    list_statistic_ids,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ileo.models import IleoReading
from custom_components.ileo.statistics import (
    DailyDelta,
    LastStatistic,
    async_import_statistics,
    build_statistics,
    compute_daily_deltas,
    statistic_ids,
)

PARIS = ZoneInfo("Europe/Paris")
ACCOUNT = "abonne@example.com"


def _r(day: int, index: float | None = None, conso: float | None = None) -> IleoReading:
    return IleoReading(date(2026, 11, day), index=index, consumption=conso)


# --- Calcul pur -------------------------------------------------------------


def test_premier_jour_sans_pic() -> None:
    """Le premier jour ne vaut jamais l'index brut."""
    deltas = compute_daily_deltas([_r(1, 123456), _r(2, 123701)])
    assert [d.delta for d in deltas] == [0.0, 245.0]


def test_premier_jour_utilise_la_consommation_fournie() -> None:
    deltas = compute_daily_deltas([_r(1, 123456, 230), _r(2, 123701, 245)])
    assert [d.delta for d in deltas] == [230.0, 245.0]


def test_index_qui_recule_ne_compte_pas() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 50), _r(4, 300)])
    assert [d.delta for d in deltas] == [0.0, 200.0, 0.0, 250.0]


def test_index_precedent_connu() -> None:
    deltas = compute_daily_deltas([_r(3, 1500)], previous_index=1200)
    assert deltas == [DailyDelta(date(2026, 11, 3), 1500, 300.0)]


def test_jour_sans_index() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, None, 80), _r(3, 1200)])
    assert [d.delta for d in deltas] == [0.0, 80.0, 200.0]


def test_build_statistics_cumul_et_minuit_local() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 1500)])
    rows = build_statistics(deltas, tz=PARIS)
    assert [row["sum"] for row in rows] == [0.0, 200.0, 500.0]
    assert [row["state"] for row in rows] == [1000, 1200, 1500]
    assert rows[1]["start"] == datetime(2026, 11, 2, tzinfo=PARIS)


def test_build_statistics_reprend_apres_la_derniere_ligne() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 1500)])
    rows = build_statistics(
        deltas, tz=PARIS, last=LastStatistic(date(2026, 11, 2), 900.0, 1200)
    )
    assert len(rows) == 1
    assert rows[0]["sum"] == 1200.0


def test_build_statistics_cout() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 3000)])
    rows = build_statistics(deltas, tz=PARIS, factor=4.5 / 1000, include_state=False)
    assert [row["sum"] for row in rows] == [0.0, 9.0]
    assert "state" not in rows[0]


def test_statistic_ids() -> None:
    assert statistic_ids(ACCOUNT) == (
        "ileo:abonne_example_com_consommation",
        "ileo:abonne_example_com_cout",
    )


# --- Import dans le recorder ------------------------------------------------


async def _stats(hass: HomeAssistant, statistic_id: str) -> list[dict]:
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return result.get(statistic_id, [])


@pytest.mark.usefixtures("paris")
async def test_import_sans_doublon_et_incremental(
    recorder_mock: Recorder, hass: HomeAssistant, hypothetical_readings
) -> None:
    consumption_id, cost_id = statistic_ids(ACCOUNT)

    await async_import_statistics(
        hass, account=ACCOUNT, name="Iléo", readings=hypothetical_readings
    )
    first = await _stats(hass, consumption_id)
    assert [row["sum"] for row in first] == [0.0, 245.0, 494.0, 724.0, 956.0]
    assert first[0]["state"] == 123456.0
    assert dt_util.utc_from_timestamp(first[0]["start"]) == datetime(
        2026, 11, 1, tzinfo=PARIS
    )

    # Réinjection du même export : rien ne change.
    await async_import_statistics(
        hass, account=ACCOUNT, name="Iléo", readings=hypothetical_readings
    )
    assert await _stats(hass, consumption_id) == first

    # Nouvel export glissant : seuls les nouveaux jours sont ajoutés.
    newer = [*hypothetical_readings[2:], IleoReading(date(2026, 11, 6), 124600.0)]
    await async_import_statistics(hass, account=ACCOUNT, name="Iléo", readings=newer)
    rows = await _stats(hass, consumption_id)
    assert [row["sum"] for row in rows] == [0.0, 245.0, 494.0, 724.0, 956.0, 1144.0]

    # Pas de prix : pas de statistique de coût.
    assert await _stats(hass, cost_id) == []

    metadata = await get_instance(hass).async_add_executor_job(
        list_statistic_ids, hass, {consumption_id}
    )
    assert metadata[0]["statistics_unit_of_measurement"] == "L"
    assert metadata[0]["has_sum"] is True
    assert metadata[0]["mean_type"] == 0
    assert metadata[0]["unit_class"] == "volume"


@pytest.mark.usefixtures("paris")
async def test_import_cout(
    recorder_mock: Recorder, hass: HomeAssistant, hypothetical_readings
) -> None:
    _, cost_id = statistic_ids(ACCOUNT)
    await async_import_statistics(
        hass,
        account=ACCOUNT,
        name="Iléo",
        readings=hypothetical_readings,
        price_per_m3=4.0,
    )
    rows = await _stats(hass, cost_id)
    assert [row["sum"] for row in rows] == pytest.approx(
        [0.0, 0.98, 1.976, 2.896, 3.824]
    )


@pytest.mark.usefixtures("paris")
async def test_import_reprend_apres_une_longue_coupure(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Si l'export ne recouvre plus le dernier jour importé, l'index sert de base."""
    consumption_id, _ = statistic_ids(ACCOUNT)
    await async_import_statistics(
        hass, account=ACCOUNT, name="Iléo", readings=[_r(1, 1000), _r(2, 1100)]
    )
    await async_wait_recording_done(hass)
    later = date(2026, 11, 2) + timedelta(days=200)
    await async_import_statistics(
        hass, account=ACCOUNT, name="Iléo", readings=[IleoReading(later, 9100.0)]
    )
    rows = await _stats(hass, consumption_id)
    assert [row["sum"] for row in rows] == [0.0, 100.0, 8100.0]
