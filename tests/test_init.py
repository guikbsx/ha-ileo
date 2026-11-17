"""Tests de mise en place, capteurs et coordinateur."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ileo.const import CONF_PRICE, CONF_PRICE_ENTITY
from custom_components.ileo.models import IleoAuthError, IleoConnectionError
from custom_components.ileo.statistics import statistic_ids

from .conftest import EMAIL


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict | None = None
) -> None:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _last_sum(hass: HomeAssistant, statistic_id: str) -> float | None:
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, False, {"sum"}
    )
    return result[statistic_id][0]["sum"] if result else None


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", "ileo", f"{entry.entry_id}_{key}"
    )
    assert entity_id
    return entity_id


@pytest.mark.usefixtures("paris")
async def test_setup_capteurs_et_statistiques(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED

    index = hass.states.get(_entity_id(hass, mock_entry, "index"))
    assert index.state == "124412.0"
    assert index.attributes["unit_of_measurement"] == "L"
    assert index.attributes["device_class"] == "water"
    assert index.attributes["state_class"] == "total_increasing"
    assert (
        hass.states.get(_entity_id(hass, mock_entry, "last_day_consumption")).state
        == "232.0"
    )
    assert (
        hass.states.get(_entity_id(hass, mock_entry, "last_reading_date")).state
        == "2026-11-05"
    )

    consumption_id, cost_id = statistic_ids(EMAIL)
    assert await _last_sum(hass, consumption_id) == 956.0
    assert await _last_sum(hass, cost_id) is None

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("paris")
async def test_cout_avec_prix_fixe(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry, {CONF_PRICE: 4.0})
    assert await _last_sum(hass, statistic_ids(EMAIL)[1]) == pytest.approx(3.824)


@pytest.mark.usefixtures("paris")
async def test_cout_avec_entite_prioritaire(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    hass.states.async_set("input_number.prix_eau", "5")
    await _setup(
        hass, mock_entry, {CONF_PRICE: 4.0, CONF_PRICE_ENTITY: "input_number.prix_eau"}
    )
    assert await _last_sum(hass, statistic_ids(EMAIL)[1]) == pytest.approx(4.78)


@pytest.mark.usefixtures("paris")
async def test_entite_de_prix_indisponible(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    hass.states.async_set("sensor.prix_eau", "unavailable")
    await _setup(hass, mock_entry, {CONF_PRICE_ENTITY: "sensor.prix_eau"})
    assert mock_entry.state is ConfigEntryState.LOADED
    assert await _last_sum(hass, statistic_ids(EMAIL)[1]) is None


async def test_export_vide(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Compteur pas encore visible sur le portail : capteurs sans valeur."""
    mock_client.async_get_readings.return_value = []
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(_entity_id(hass, mock_entry, "index")).state == "unknown"


async def test_portail_injoignable(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_get_readings.side_effect = IleoConnectionError
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_identifiants_refuses_declenche_reauth(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_get_readings.side_effect = IleoAuthError
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]
