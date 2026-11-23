"""Tests of the config flow."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ileo.const import (
    CONF_CONTRACT,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    DOMAIN,
)
from custom_components.ileo.models import (
    IleoAuthError,
    IleoConnectionError,
    IleoContract,
    IleoResponseError,
)

from .conftest import CONTRACT, EMAIL, OTHER_CONTRACT, PASSWORD

CREDENTIALS = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}
ONE_CONTRACT = [IleoContract(CONTRACT, "Home")]
TWO_CONTRACTS = [IleoContract(CONTRACT, "Home"), IleoContract(OTHER_CONTRACT)]


@pytest.fixture
def mock_login() -> Generator[AsyncMock]:
    with patch(
        "custom_components.ileo.config_flow.IleoClient.async_login",
        autospec=True,
        return_value=ONE_CONTRACT,
    ) as login:
        yield login


@pytest.fixture
def mock_setup() -> Generator[AsyncMock]:
    with patch("custom_components.ileo.async_setup_entry", return_value=True) as setup:
        yield setup


async def _submit_credentials(hass: HomeAssistant, **overrides: str) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CREDENTIALS, **overrides}
    )


@pytest.mark.usefixtures("mock_setup", "mock_login")
async def test_user_with_one_contract(hass: HomeAssistant) -> None:
    result = await _submit_credentials(hass, **{CONF_EMAIL: " Subscriber@Example.com "})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Iléo {CONTRACT}"
    assert result["data"] == {**CREDENTIALS, CONF_CONTRACT: CONTRACT}
    assert result["result"].unique_id == CONTRACT


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (IleoAuthError, "invalid_auth"),
        (IleoConnectionError, "cannot_connect"),
        (IleoResponseError, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup")
async def test_user_errors_then_success(
    hass: HomeAssistant, mock_login: AsyncMock, exc: type[Exception], error: str
) -> None:
    mock_login.side_effect = exc
    result = await _submit_credentials(hass, **{CONF_PASSWORD: "wrong"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_login")
async def test_contract_already_configured(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await _submit_credentials(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup")
async def test_user_picks_one_of_several_contracts(
    hass: HomeAssistant, mock_login: AsyncMock
) -> None:
    mock_login.return_value = TWO_CONTRACTS
    result = await _submit_credentials(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "contract"
    selector = result["data_schema"].schema[CONF_CONTRACT]
    assert selector.config["options"] == [
        {"value": CONTRACT, "label": f"{CONTRACT} – Home"},
        {"value": OTHER_CONTRACT, "label": OTHER_CONTRACT},
    ]

    # The portal must confirm it can select the contract before the entry is created.
    mock_login.side_effect = IleoResponseError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CONTRACT: OTHER_CONTRACT}
    )
    assert result["step_id"] == "contract"
    assert result["errors"] == {"base": "unknown"}

    mock_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CONTRACT: OTHER_CONTRACT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**CREDENTIALS, CONF_CONTRACT: OTHER_CONTRACT}
    assert result["result"].unique_id == OTHER_CONTRACT
    assert mock_login.call_args.args[0]._contract == OTHER_CONTRACT


@pytest.mark.usefixtures("mock_setup")
async def test_remaining_contract_added_directly(
    hass: HomeAssistant, mock_login: AsyncMock, mock_entry: MockConfigEntry
) -> None:
    """Adding the account again offers only the contracts not followed yet."""
    mock_entry.add_to_hass(hass)
    mock_login.return_value = TWO_CONTRACTS

    result = await _submit_credentials(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == OTHER_CONTRACT


@pytest.mark.usefixtures("mock_setup")
async def test_reauth(
    hass: HomeAssistant, mock_login: AsyncMock, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_login.side_effect = IleoAuthError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_PASSWORD] == "new"
    # The new password is checked against the contract of the entry.
    assert mock_login.call_args.args[0]._contract == CONTRACT


@pytest.mark.usefixtures("mock_setup")
async def test_options(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRICE: 4.12, CONF_PRICE_ENTITY: "sensor.water_price"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options == {
        CONF_PRICE: 4.12,
        CONF_PRICE_ENTITY: "sensor.water_price",
    }
