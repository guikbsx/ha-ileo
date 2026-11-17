"""Configuration de l'intégration Iléo depuis l'interface."""

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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import IleoClient
from .const import CONF_PRICE, CONF_PRICE_ENTITY, DOMAIN
from .coordinator import IleoConfigEntry
from .models import IleoAuthError, IleoConnectionError, IleoError

_LOGGER = logging.getLogger(__name__)

_EMAIL_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
)
_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): _EMAIL_SELECTOR,
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR})
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PRICE): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=100,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="€/m³",
            )
        ),
        vol.Optional(CONF_PRICE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_number", "number"])
        ),
    }
)


async def _async_validate(
    hass: HomeAssistant, email: str, password: str
) -> dict[str, str]:
    """Essaie de se connecter ; retourne les erreurs du formulaire."""
    session = async_create_clientsession(hass, auto_cleanup=False)
    try:
        await IleoClient(session, email, password).async_login()
    except IleoAuthError:
        return {"base": "invalid_auth"}
    except IleoConnectionError:
        return {"base": "cannot_connect"}
    except IleoError:
        _LOGGER.exception("Réponse inattendue du portail Iléo")
        return {"base": "unknown"}
    finally:
        session.detach()
    return {}


class IleoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'un compte Iléo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            errors = await _async_validate(self.hass, email, password)
            if not errors:
                return self.async_create_entry(
                    title=email, data={CONF_EMAIL: email, CONF_PASSWORD: password}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, {CONF_EMAIL: (user_input or {}).get(CONF_EMAIL)}
            ),
            errors=errors,
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
            errors = await _async_validate(
                self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
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
    """Options : prix de l'eau pour la statistique de coût."""

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
