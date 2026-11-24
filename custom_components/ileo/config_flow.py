"""Config flow of the Iléo integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio

from .api import IleoClient
from .const import CONF_CONTRACT, CONF_PRICE, CONF_PRICE_ENTITY, DOMAIN
from .coordinator import IleoConfigEntry
from .models import IleoAuthError, IleoConnectionError, IleoContract, IleoError

_LOGGER = logging.getLogger(__name__)

_EMAIL_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
)
_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_EMAIL): _EMAIL_SELECTOR,
        probatio.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)
STEP_REAUTH_SCHEMA = probatio.Schema(
    {probatio.Required(CONF_PASSWORD): _PASSWORD_SELECTOR}
)
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_PRICE): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=100,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="€/m³",
            )
        ),
        probatio.Optional(CONF_PRICE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_number", "number"])
        ),
    }
)


async def _async_login(
    hass: HomeAssistant, email: str, password: str, contract: str | None = None
) -> tuple[list[IleoContract], dict[str, str]]:
    """Try to sign in; return the contracts of the account and the form errors.

    With `contract`, also check that the portal can select that contract.
    """
    session = async_create_clientsession(hass, auto_cleanup=False)
    try:
        client = IleoClient(session, email, password, contract=contract)
        return await client.async_login(), {}
    except IleoAuthError:
        return [], {"base": "invalid_auth"}
    except IleoConnectionError:
        return [], {"base": "cannot_connect"}
    except IleoError:
        _LOGGER.exception("Unexpected response from the Iléo portal")
        return [], {"base": "unknown"}
    finally:
        session.detach()


class IleoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a contract of an Iléo account.

    One config entry follows one contract: an account with several contracts
    is added once per contract.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._contracts: list[IleoContract] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            password = user_input[CONF_PASSWORD]
            contracts, errors = await _async_login(self.hass, email, password)
            if not errors:
                configured = self._async_current_ids()
                self._credentials = {CONF_EMAIL: email, CONF_PASSWORD: password}
                self._contracts = [c for c in contracts if c.number not in configured]
                if not self._contracts:
                    return self.async_abort(reason="already_configured")
                if len(self._contracts) == 1:
                    return await self._async_create_entry(self._contracts[0].number)
                return await self.async_step_contract()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, {CONF_EMAIL: (user_input or {}).get(CONF_EMAIL)}
            ),
            errors=errors,
        )

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of the contracts of the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            contract = user_input[CONF_CONTRACT]
            _, errors = await _async_login(
                self.hass, **self._credentials, contract=contract
            )
            if not errors:
                return await self._async_create_entry(contract)
        options = [
            SelectOptionDict(
                value=c.number, label=f"{c.number} – {c.label}" if c.label else c.number
            )
            for c in self._contracts
        ]
        return self.async_show_form(
            step_id="contract",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_CONTRACT): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_create_entry(self, contract: str) -> ConfigFlowResult:
        await self.async_set_unique_id(contract)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Iléo {contract}",
            data={**self._credentials, CONF_CONTRACT: contract},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _, errors = await _async_login(
                self.hass,
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                entry.data[CONF_CONTRACT],
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: IleoConfigEntry) -> IleoOptionsFlow:
        return IleoOptionsFlow()


class IleoOptionsFlow(OptionsFlowWithReload):
    """Options: water price used for the cost statistic."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
