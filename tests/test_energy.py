"""The imported statistics must be usable as a water source of the Energy dashboard."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.energy import data as energy_data, validate
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ileo.const import CONF_PRICE
from custom_components.ileo.statistics import statistic_ids

from .conftest import CONTRACT

PARIS = ZoneInfo("Europe/Paris")
CONSUMPTION_ID, COST_ID = statistic_ids(CONTRACT)


async def _daily_changes(hass: HomeAssistant, statistic_id: str) -> dict[str, float]:
    """Return what the dashboard plots: the change of the sum for each local day."""
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 10, 31, tzinfo=PARIS),
        None,
        {statistic_id},
        "day",
        None,
        {"change"},
    )
    return {
        dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date().isoformat(): (
            row["change"]
        )
        for row in result[statistic_id]
    }


@pytest.mark.usefixtures("paris", "mock_client")
async def test_statistics_are_a_valid_water_source(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_entry, options={CONF_PRICE: 4.0})
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    # Configure the dashboard the way the UI does for a water source with its
    # own cost statistic.
    assert await async_setup_component(hass, "energy", {})
    manager = await energy_data.async_get_manager(hass)
    await manager.async_update(
        {
            "energy_sources": [
                {
                    "type": "water",
                    "stat_energy_from": CONSUMPTION_ID,
                    "stat_cost": COST_ID,
                    "entity_energy_price": None,
                    "number_energy_price": None,
                }
            ]
        }
    )

    # Home Assistant's own validation of the dashboard finds nothing to report.
    result = (await validate.async_validate(hass)).as_dict()
    assert result["energy_sources"] == [[]]

    # Each day shows its own consumption, on the day the water was used.
    assert await _daily_changes(hass, CONSUMPTION_ID) == {
        "2026-11-01": 0.0,
        "2026-11-02": 245.0,
        "2026-11-03": 249.0,
        "2026-11-04": 230.0,
        "2026-11-05": 232.0,
    }
    assert await _daily_changes(hass, COST_ID) == pytest.approx(
        {
            "2026-11-01": 0.0,
            "2026-11-02": 0.98,
            "2026-11-03": 0.996,
            "2026-11-04": 0.92,
            "2026-11-05": 0.928,
        }
    )


def test_dashboard_refuses_its_own_price_for_external_statistics() -> None:
    """Why the integration has its own price option and cost statistic.

    The dashboard cannot compute a cost from a price for an external statistic,
    so the cost has to be provided as a statistic.
    """
    source = {"type": "water", "stat_energy_from": CONSUMPTION_ID}

    with pytest.raises(Exception, match="xternal"):
        energy_data.WATER_SOURCE_SCHEMA({**source, "number_energy_price": 4.0})

    accepted = energy_data.WATER_SOURCE_SCHEMA({**source, "stat_cost": COST_ID})
    assert accepted["stat_cost"] == COST_ID
