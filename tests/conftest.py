"""Fixtures communes."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.components.recorder import Recorder
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ileo.const import DOMAIN
from custom_components.ileo.parser import decode_export, parse_export_csv

FIXTURES = Path(__file__).parent / "fixtures"
EMAIL = "abonne@example.com"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Recorder en mémoire (dépendance de l'intégration) et intégrations perso actives.

    `recorder_mock` doit être initialisé avant `hass`, d'où sa place ici.
    """


@pytest.fixture
async def paris(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
    )


@pytest.fixture
def hypothetical_readings():
    """Relevés issus de l'export HYPOTHÉTIQUE."""
    return parse_export_csv(
        decode_export(load_fixture_bytes("export_hypothetique.csv"))
    )


@pytest.fixture
def mock_client(hypothetical_readings) -> Generator[AsyncMock]:
    """Remplace le client Iléo (aucun accès réseau)."""
    with patch("custom_components.ileo.IleoClient", autospec=True) as client_cls:
        client = client_cls.return_value
        client.async_get_readings.return_value = hypothetical_readings
        yield client
