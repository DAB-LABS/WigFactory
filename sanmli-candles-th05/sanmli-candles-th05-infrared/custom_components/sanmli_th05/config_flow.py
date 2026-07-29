"""Config flow for the Sanmli TH-05 candle integration."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant.components.infrared import (
    DOMAIN as INFRARED_DOMAIN,
)
from homeassistant.components.infrared import (
    async_get_emitters,
    async_get_receivers,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_INFRARED_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DEVICE_NAME,
    DOMAIN,
)


@callback
def _schema(hass: HomeAssistant) -> vol.Schema:
    """Emitter and optional receiver selection."""
    return vol.Schema(
        {
            vol.Required(CONF_INFRARED_ENTITY_ID): EntitySelector(
                EntitySelectorConfig(
                    domain=INFRARED_DOMAIN,
                    include_entities=async_get_emitters(hass),
                )
            ),
            # Optional everywhere in this ecosystem: plenty of people have a
            # blaster and no receiver, and the candles work fine without one.
            # Without it the event entity is simply not created.
            vol.Optional(CONF_INFRARED_RECEIVER_ENTITY_ID): EntitySelector(
                EntitySelectorConfig(
                    domain=INFRARED_DOMAIN,
                    include_entities=async_get_receivers(hass),
                )
            ),
        }
    )


class Th05ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the candle config flow."""

    VERSION = 1

    def _entity_name(self, entity_id: str) -> str:
        """Return an entity's friendly name, falling back to its id."""
        ent_reg = er.async_get(self.hass)
        entry = ent_reg.async_get(entity_id)
        return entry.name or entry.original_name or entity_id if entry else entity_id

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the emitter, and optionally a receiver."""
        if not async_get_emitters(self.hass):
            return self.async_abort(reason="no_infrared_entities")

        if user_input is not None:
            emitter_id = user_input[CONF_INFRARED_ENTITY_ID]
            self._async_abort_entries_match(
                {CONF_INFRARED_ENTITY_ID: emitter_id}
            )
            return self.async_create_entry(
                title=f"{DEVICE_NAME} via {self._entity_name(emitter_id)}",
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=_schema(self.hass))
