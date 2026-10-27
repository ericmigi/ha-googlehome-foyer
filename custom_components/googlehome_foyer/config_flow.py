from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from . import CONF_ANDROID_ID, CONF_MASTER_TOKEN, CONF_PIN, DOMAIN
from .api import FoyerAuthError, FoyerClient, FoyerError, exchange_oauth_token

CONF_OAUTH_TOKEN = "oauth_token"
CONF_EMAIL = "email"
CONF_CLEAR_PIN = "clear_pin"
SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_OAUTH_TOKEN): SECRET,
        vol.Optional(CONF_MASTER_TOKEN): SECRET,
        vol.Optional(CONF_EMAIL): str,
    }
)


class FoyerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # oauth_token cookies are single-use: keep an exchanged master token if we still need the email.
    _pending: tuple[str, str] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            oauth = (user_input.get(CONF_OAUTH_TOKEN) or "").strip()
            master = (user_input.get(CONF_MASTER_TOKEN) or "").strip()
            email = (user_input.get(CONF_EMAIL) or "").strip()
            session = async_get_clientsession(self.hass)
            android_id = secrets.token_hex(8)
            if not master and not oauth and self._pending:
                master, android_id = self._pending
            try:
                if not master and oauth:
                    master, google_email = await exchange_oauth_token(session, oauth, android_id)
                    email = google_email or email
                    self._pending = (master, android_id)
                if not master:
                    errors["base"] = "missing_token"
                elif not email:
                    # The account email is the entry's identity; gpsoauth only returns it sometimes.
                    errors[CONF_EMAIL] = "email_required"
                else:
                    await FoyerClient(session, master, android_id).home_graph()
            except FoyerAuthError:
                errors["base"] = "invalid_auth"
            except FoyerError:
                errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(email.lower())
                data = {CONF_MASTER_TOKEN: master, CONF_ANDROID_ID: android_id}
                if self.source == "reauth":
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=email, data=data)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return FoyerOptionsFlow()


class FoyerOptionsFlow(OptionsFlow):
    """Lock PIN: blank keeps the saved one, a new value replaces it, clear_pin removes it."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        saved = self.config_entry.options.get(CONF_PIN, "")
        if user_input is not None:
            pin = (user_input.get(CONF_PIN) or "").replace(" ", "").replace("-", "")
            if user_input.get(CONF_CLEAR_PIN):
                return self.async_create_entry(data={CONF_PIN: ""})
            if not pin:
                return self.async_create_entry(data={CONF_PIN: saved})
            if len(pin) < 4 or not pin.isdigit():
                errors[CONF_PIN] = "invalid_pin"
            else:
                return self.async_create_entry(data={CONF_PIN: pin})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_PIN): SECRET, vol.Optional(CONF_CLEAR_PIN, default=False): bool}
            ),
            description_placeholders={"status": "A PIN is saved." if saved else "No PIN saved."},
            errors=errors,
        )
