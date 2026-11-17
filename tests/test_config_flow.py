"""Tests du parcours de configuration."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ileo.const import CONF_PRICE, CONF_PRICE_ENTITY, DOMAIN
from custom_components.ileo.models import (
    IleoAuthError,
    IleoConnectionError,
    IleoResponseError,
)

from .conftest import EMAIL


@pytest.fixture
def mock_login() -> Generator[AsyncMock]:
    with patch(
        "custom_components.ileo.config_flow.IleoClient.async_login", autospec=True
    ) as login:
        yield login


@pytest.fixture
def mock_setup() -> Generator[AsyncMock]:
    with patch("custom_components.ileo.async_setup_entry", return_value=True) as setup:
        yield setup


@pytest.mark.usefixtures("mock_setup")
async def test_user_ok(hass: HomeAssistant, mock_login: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: " Abonne@Example.com ", CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"}
    assert result["result"].unique_id == EMAIL


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (IleoAuthError, "invalid_auth"),
        (IleoConnectionError, "cannot_connect"),
        (IleoResponseError, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup")
async def test_user_erreurs_puis_ok(
    hass: HomeAssistant, mock_login: AsyncMock, exc: type[Exception], error: str
) -> None:
    mock_login.side_effect = exc
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: "faux"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_deja_configure(
    hass: HomeAssistant, mock_login: AsyncMock, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_login.assert_not_called()


@pytest.mark.usefixtures("mock_setup")
async def test_reauth(
    hass: HomeAssistant, mock_login: AsyncMock, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_login.side_effect = IleoAuthError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "toujours-faux"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "nouveau"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_PASSWORD] == "nouveau"


@pytest.mark.usefixtures("mock_setup")
async def test_options(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRICE: 4.12, CONF_PRICE_ENTITY: "sensor.prix_eau"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options == {
        CONF_PRICE: 4.12,
        CONF_PRICE_ENTITY: "sensor.prix_eau",
    }
