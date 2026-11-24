"""Tests of the setup, the sensors, the coordinator and the diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.icon import async_get_icons
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ileo.const import (
    CONF_CONTRACT,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    DOMAIN,
)
from custom_components.ileo.coordinator import contract_issue_id
from custom_components.ileo.diagnostics import async_get_config_entry_diagnostics
from custom_components.ileo.models import (
    IleoAuthError,
    IleoConnectionError,
    IleoContractError,
    IleoParseError,
)
from custom_components.ileo.statistics import statistic_ids

from .conftest import CONTRACT, EMAIL, PASSWORD

CONSUMPTION_ID, COST_ID = statistic_ids(CONTRACT)


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


def _entity_id(hass: HomeAssistant, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{CONTRACT}_{key}"
    )
    assert entity_id
    return entity_id


@pytest.mark.usefixtures("paris")
async def test_setup_sensors_and_statistics(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED

    index = hass.states.get(_entity_id(hass, "index"))
    assert index.state == "124412.0"
    assert index.attributes["unit_of_measurement"] == "L"
    assert index.attributes["device_class"] == "water"
    assert index.attributes["state_class"] == "total_increasing"
    assert hass.states.get(_entity_id(hass, "last_day_consumption")).state == "232.0"
    assert hass.states.get(_entity_id(hass, "last_reading_date")).state == "2026-11-05"

    assert await _last_sum(hass, CONSUMPTION_ID) == 956.0
    assert await _last_sum(hass, COST_ID) is None

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.NOT_LOADED


async def test_client_reads_the_configured_contract(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """The client is told which contract to read, never left to the portal's default."""
    with pytest.MonkeyPatch.context() as patcher:
        calls: list[tuple] = []

        class FakeClient:
            def __init__(self, session, email, password, *, contract) -> None:
                calls.append((email, password, contract))

            async def async_get_readings(self, start, end) -> list:
                return []

        patcher.setattr("custom_components.ileo.IleoClient", FakeClient)
        await _setup(hass, mock_entry)

    assert calls == [(EMAIL, PASSWORD, CONTRACT)]


async def test_device_and_entity_category(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry)
    (device,) = dr.async_entries_for_config_entry(
        dr.async_get(hass), mock_entry.entry_id
    )
    assert device.identifiers == {(DOMAIN, CONTRACT)}
    assert device.name == "Water meter"
    assert device.serial_number == CONTRACT
    entry = er.async_get(hass).async_get(_entity_id(hass, "last_reading_date"))
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


# --- Water price ----------------------------------------------------------------


@pytest.mark.usefixtures("paris")
async def test_cost_with_fixed_price(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry, {CONF_PRICE: 4.0})
    assert await _last_sum(hass, COST_ID) == pytest.approx(3.824)


@pytest.mark.usefixtures("paris")
async def test_cost_with_entity_taking_precedence(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    hass.states.async_set("input_number.water_price", "5")
    await _setup(
        hass,
        mock_entry,
        {CONF_PRICE: 4.0, CONF_PRICE_ENTITY: "input_number.water_price"},
    )
    assert await _last_sum(hass, COST_ID) == pytest.approx(4.78)


@pytest.mark.usefixtures("paris")
@pytest.mark.parametrize("state", ["unavailable", "nan", "inf", "-3", "free"])
async def test_unusable_price_entity(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock, state: str
) -> None:
    """An unavailable, negative or non-finite price creates no cost statistic."""
    hass.states.async_set("sensor.water_price", state)
    await _setup(
        hass, mock_entry, {CONF_PRICE: 4.0, CONF_PRICE_ENTITY: "sensor.water_price"}
    )
    assert mock_entry.state is ConfigEntryState.LOADED
    assert await _last_sum(hass, COST_ID) is None


# --- Export content and failures ------------------------------------------------


async def test_empty_export(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Meter not visible on the portal yet: sensors without a value."""
    mock_client.async_get_readings.return_value = []
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(_entity_id(hass, "index")).state == "unknown"


@pytest.mark.usefixtures("paris")
@pytest.mark.freeze_time("2026-11-03 12:00:00+01:00")
async def test_days_in_the_future_ignored(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The synthetic export runs until 05/11: only days up to today count."""
    await _setup(hass, mock_entry)
    assert hass.states.get(_entity_id(hass, "last_reading_date")).state == "2026-11-03"
    assert await _last_sum(hass, CONSUMPTION_ID) == 494.0


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (IleoConnectionError("Iléo server error (HTTP 503)"), "Unable to reach"),
        (IleoParseError("Header of the export not found"), "unexpected response"),
    ],
)
async def test_portal_failure_retries_with_translated_reason(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_client: AsyncMock,
    exc: Exception,
    reason: str,
) -> None:
    mock_client.async_get_readings.side_effect = exc
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY
    assert reason in mock_entry.reason
    assert str(exc) not in mock_entry.reason


async def test_rejected_credentials_start_reauth(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_get_readings.side_effect = IleoAuthError
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


# --- Diagnostics ----------------------------------------------------------------


@pytest.mark.usefixtures("paris")
async def test_diagnostics_without_personal_data(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert diagnostics["state"] == "loaded"
    assert diagnostics["coordinator"] == {
        "last_update_success": True,
        "readings": 5,
        "first_day": "2026-11-01",
        "last_day": "2026-11-05",
        "with_index": 5,
    }
    dump = json.dumps(diagnostics, default=str)
    assert EMAIL not in dump
    assert PASSWORD not in dump
    assert CONTRACT not in dump
    assert diagnostics["entry"]["data"] == {
        CONF_EMAIL: "**REDACTED**",
        CONF_PASSWORD: "**REDACTED**",
        CONF_CONTRACT: "**REDACTED**",
    }


async def test_diagnostics_when_setup_failed(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Portal down: diagnostics can still be downloaded."""
    mock_client.async_get_readings.side_effect = IleoConnectionError
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert diagnostics["state"] == "setup_retry"
    assert diagnostics["coordinator"] is None
    assert EMAIL not in json.dumps(diagnostics, default=str)


# --- Repairs --------------------------------------------------------------------


async def test_lost_contract_raises_a_repair_issue_until_it_is_back(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The user can fix a lost contract: Repairs says so, then forgets it."""
    issues = ir.async_get(hass)
    issue_id = contract_issue_id(CONTRACT)

    mock_client.async_get_readings.side_effect = IleoContractError
    await _setup(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY
    assert "contract" in mock_entry.reason
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_placeholders == {"contract": CONTRACT}

    mock_client.async_get_readings.side_effect = None
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_removing_the_entry_clears_its_repair_issue(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_get_readings.side_effect = IleoContractError
    await _setup(hass, mock_entry)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, contract_issue_id(CONTRACT)) is not None

    await hass.config_entries.async_remove(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, contract_issue_id(CONTRACT)) is None


async def test_sensor_icons(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, mock_entry)
    icons = await async_get_icons(hass, "entity", integrations=[DOMAIN])
    assert set(icons[DOMAIN]["sensor"]) == {
        "index",
        "last_day_consumption",
        "last_reading_date",
    }
