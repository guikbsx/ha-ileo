"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.components.recorder import Recorder
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ileo.const import CONF_CONTRACT, DOMAIN
from custom_components.ileo.models import IleoContract, IleoReading
from custom_components.ileo.parser import decode_export, parse_export_csv

FIXTURES = Path(__file__).parent / "fixtures"
EMAIL = "subscriber@example.com"
PASSWORD = "secret"
CONTRACT = "1234567"
OTHER_CONTRACT = "7654321"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """In-memory recorder (a dependency of the integration) and custom integrations on.

    `recorder_mock` must be set up before `hass`, hence its place here.
    """


@pytest.fixture
async def paris(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Iléo {CONTRACT}",
        unique_id=CONTRACT,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, CONF_CONTRACT: CONTRACT},
    )


@pytest.fixture
def synthetic_readings() -> list[IleoReading]:
    """Readings of the synthetic export (values chosen for the tests)."""
    return parse_export_csv(decode_export(load_fixture_bytes("export_synthetic.csv")))


@pytest.fixture
def mock_client(synthetic_readings: list[IleoReading]) -> Generator[AsyncMock]:
    """Replace the Iléo client (no network access)."""
    with patch("custom_components.ileo.IleoClient", autospec=True) as client_cls:
        client = client_cls.return_value
        client.async_login.return_value = [IleoContract(CONTRACT)]
        client.async_get_readings.return_value = synthetic_readings
        yield client
