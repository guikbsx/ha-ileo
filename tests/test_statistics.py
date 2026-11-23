"""Tests of the statistics computation and import."""

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
    statistic_names,
)

PARIS = ZoneInfo("Europe/Paris")
CONTRACT = "1234567"


def _r(day: int, index: float | None = None, conso: float | None = None) -> IleoReading:
    return IleoReading(date(2026, 11, day), index=index, consumption=conso)


# --- Pure computation ---------------------------------------------------------


def test_first_day_without_spike() -> None:
    """The first day is never worth the raw index."""
    deltas = compute_daily_deltas([_r(1, 123456), _r(2, 123701)])
    assert [d.delta for d in deltas] == [0.0, 245.0]


def test_first_day_uses_the_given_consumption() -> None:
    deltas = compute_daily_deltas([_r(1, 123456, 230), _r(2, 123701, 245)])
    assert [d.delta for d in deltas] == [230.0, 245.0]


def test_index_going_backwards_counts_for_nothing() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 50), _r(4, 300)])
    assert [d.delta for d in deltas] == [0.0, 200.0, 0.0, 250.0]


def test_known_previous_index() -> None:
    deltas = compute_daily_deltas([_r(3, 1500)], previous_index=1200)
    assert deltas == [DailyDelta(date(2026, 11, 3), 1500, 300.0)]


def test_day_without_index() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, None, 80), _r(3, 1200)])
    assert [d.delta for d in deltas] == [0.0, 80.0, 200.0]


def test_build_statistics_running_total_at_local_midnight() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 1500)])
    rows = build_statistics(deltas, tz=PARIS)
    assert [row["sum"] for row in rows] == [0.0, 200.0, 500.0]
    assert [row["state"] for row in rows] == [1000, 1200, 1500]
    assert rows[1]["start"] == datetime(2026, 11, 2, tzinfo=PARIS)


def test_build_statistics_resumes_after_the_last_row() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 1200), _r(3, 1500)])
    rows = build_statistics(
        deltas, tz=PARIS, last=LastStatistic(date(2026, 11, 2), 900.0, 1200)
    )
    assert len(rows) == 1
    assert rows[0]["sum"] == 1200.0


def test_build_statistics_cost() -> None:
    deltas = compute_daily_deltas([_r(1, 1000), _r(2, 3000)])
    rows = build_statistics(deltas, tz=PARIS, factor=4.5 / 1000, include_state=False)
    assert [row["sum"] for row in rows] == [0.0, 9.0]
    assert "state" not in rows[0]


def test_statistic_ids() -> None:
    assert statistic_ids(CONTRACT) == (
        "ileo:1234567_water_consumption",
        "ileo:1234567_water_cost",
    )


def test_statistic_names() -> None:
    assert statistic_names(CONTRACT, "fr") == (
        "Iléo 1234567 – consommation d'eau",
        "Iléo 1234567 – coût de l'eau",
    )
    assert statistic_names(CONTRACT, "de") == (
        "Iléo 1234567 water consumption",
        "Iléo 1234567 water cost",
    )


# --- Import into the recorder -------------------------------------------------


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
async def test_import_is_incremental_without_duplicates(
    recorder_mock: Recorder, hass: HomeAssistant, synthetic_readings
) -> None:
    consumption_id, cost_id = statistic_ids(CONTRACT)

    await async_import_statistics(hass, contract=CONTRACT, readings=synthetic_readings)
    first = await _stats(hass, consumption_id)
    assert [row["sum"] for row in first] == [0.0, 245.0, 494.0, 724.0, 956.0]
    assert first[0]["state"] == 123456.0
    assert dt_util.utc_from_timestamp(first[0]["start"]) == datetime(
        2026, 11, 1, tzinfo=PARIS
    )

    # Importing the same export again changes nothing.
    await async_import_statistics(hass, contract=CONTRACT, readings=synthetic_readings)
    assert await _stats(hass, consumption_id) == first

    # Newer sliding export: only the new days are added.
    newer = [*synthetic_readings[2:], IleoReading(date(2026, 11, 6), 124600.0)]
    await async_import_statistics(hass, contract=CONTRACT, readings=newer)
    rows = await _stats(hass, consumption_id)
    assert [row["sum"] for row in rows] == [0.0, 245.0, 494.0, 724.0, 956.0, 1144.0]

    # No price: no cost statistic.
    assert await _stats(hass, cost_id) == []

    metadata = await get_instance(hass).async_add_executor_job(
        list_statistic_ids, hass, {consumption_id}
    )
    assert metadata[0]["statistics_unit_of_measurement"] == "L"
    assert metadata[0]["has_sum"] is True
    assert metadata[0]["mean_type"] == 0
    assert metadata[0]["unit_class"] == "volume"
    assert metadata[0]["name"] == "Iléo 1234567 water consumption"


@pytest.mark.usefixtures("paris")
async def test_import_cost(
    recorder_mock: Recorder, hass: HomeAssistant, synthetic_readings
) -> None:
    _, cost_id = statistic_ids(CONTRACT)
    await async_import_statistics(
        hass,
        contract=CONTRACT,
        readings=synthetic_readings,
        price_per_m3=4.0,
    )
    rows = await _stats(hass, cost_id)
    assert [row["sum"] for row in rows] == pytest.approx(
        [0.0, 0.98, 1.976, 2.896, 3.824]
    )


@pytest.mark.usefixtures("paris")
async def test_import_resumes_after_a_long_gap(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """If the export no longer overlaps the last imported day, its index is the baseline."""
    consumption_id, _ = statistic_ids(CONTRACT)
    await async_import_statistics(
        hass, contract=CONTRACT, readings=[_r(1, 1000), _r(2, 1100)]
    )
    await async_wait_recording_done(hass)
    later = date(2026, 11, 2) + timedelta(days=200)
    await async_import_statistics(
        hass, contract=CONTRACT, readings=[IleoReading(later, 9100.0)]
    )
    rows = await _stats(hass, consumption_id)
    assert [row["sum"] for row in rows] == [0.0, 100.0, 8100.0]


@pytest.mark.usefixtures("paris")
async def test_price_added_after_the_first_import(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A cost statistic started later prices every day of the export, the first too.

    The last imported index is a baseline only for readings that come after it:
    used for an older reading, it would make that day worth nothing.
    """
    consumption_id, cost_id = statistic_ids(CONTRACT)
    readings = [_r(1, 1000, 80), _r(2, 1200, 200), _r(3, 1500, 300)]

    await async_import_statistics(hass, contract=CONTRACT, readings=readings)
    assert [row["sum"] for row in await _stats(hass, consumption_id)] == [
        80.0,
        280.0,
        580.0,
    ]

    deltas = await async_import_statistics(
        hass, contract=CONTRACT, readings=readings, price_per_m3=4.0
    )
    assert [d.delta for d in deltas] == [80.0, 200.0, 300.0]
    assert [row["sum"] for row in await _stats(hass, cost_id)] == pytest.approx(
        [0.32, 1.12, 2.32]
    )


async def test_import_nothing(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    assert await async_import_statistics(hass, contract=CONTRACT, readings=[]) == []
