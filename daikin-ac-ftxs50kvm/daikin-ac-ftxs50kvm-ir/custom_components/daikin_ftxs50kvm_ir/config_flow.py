"""Config flow for the Daikin FTXS50KVM infrared integration."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol

from homeassistant.components.infrared import (
    DOMAIN as INFRARED_DOMAIN,
    async_get_emitters,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_INFRARED_ENTITY_ID,
    CONF_SEND_COUNT,
    DEFAULT_SEND_COUNT,
    DEVICE_NAME,
    DOMAIN,
    MAX_SEND_COUNT,
    MIN_SEND_COUNT,
)


def _send_count_selector() -> NumberSelector:
    """Build the sends-per-change picker, shared by both flows."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SEND_COUNT,
            max=MAX_SEND_COUNT,
            step=1,
            mode=NumberSelectorMode.BOX,
        )
    )


@callback
def _user_schema(hass: HomeAssistant) -> vol.Schema:
    """Build the setup schema: the emitter, and sends per change."""
    return vol.Schema(
        {
            vol.Required(CONF_INFRARED_ENTITY_ID): EntitySelector(
                EntitySelectorConfig(
                    domain=INFRARED_DOMAIN,
                    include_entities=async_get_emitters(hass),
                )
            ),
            vol.Required(
                CONF_SEND_COUNT, default=DEFAULT_SEND_COUNT
            ): _send_count_selector(),
        }
    )


class DaikinConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Daikin config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DaikinOptionsFlow:
        """Return the options flow."""
        return DaikinOptionsFlow()

    def _entity_name(self, entity_id: str) -> str:
        """Return an entity's friendly name, falling back to its id."""
        ent_reg = er.async_get(self.hass)
        entry = ent_reg.async_get(entity_id)
        return entry.name or entry.original_name or entity_id if entry else entity_id

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the emitter that can reach the indoor unit."""
        if not async_get_emitters(self.hass):
            return self.async_abort(reason="no_infrared_entities")

        if user_input is not None:
            emitter_id = user_input[CONF_INFRARED_ENTITY_ID]
            self._async_abort_entries_match({CONF_INFRARED_ENTITY_ID: emitter_id})
            return self.async_create_entry(
                title=f"{DEVICE_NAME} via {self._entity_name(emitter_id)}",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(self.hass)
        )


class DaikinOptionsFlow(OptionsFlowWithReload):
    """Change how many times each change transmits, after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the sends-per-change setting."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SEND_COUNT,
            self.config_entry.data.get(CONF_SEND_COUNT, DEFAULT_SEND_COUNT),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SEND_COUNT, default=current): _send_count_selector()}
            ),
        )
