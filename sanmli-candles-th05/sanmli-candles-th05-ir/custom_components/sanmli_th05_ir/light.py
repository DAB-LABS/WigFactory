"""Light platform: on, off, and the four lighting effects.

Deliberately no brightness. The candle has Brighten Up and Dim Down, which are
relative steps with no absolute levels, no feedback path and no known step
count. Home Assistant's brightness contract is absolute, so honouring it would
mean reporting a number nobody measured: press dim at the floor, or pick up the
physical remote, and the reported brightness silently stops matching the room.
The two steps are buttons instead, where a press means a press. This
integration would rather expose less than claim more than it knows.
"""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Th05ConfigEntry
from .codes import SanmliTh05Code
from .const import CONF_INFRARED_ENTITY_ID
from .entity import Th05EmitterEntity

PARALLEL_UPDATES = 1

EFFECT_CANDLE = "Candle"
EFFECT_FLICKER = "Flicker"
EFFECT_FADE_OUT = "Fade out"
EFFECT_SOLID = "Solid"

_EFFECT_TO_CODE: dict[str, SanmliTh05Code] = {
    EFFECT_CANDLE: SanmliTh05Code.CANDLE_LIKE,
    EFFECT_FLICKER: SanmliTh05Code.FLICKER,
    EFFECT_FADE_OUT: SanmliTh05Code.FADE_OUT,
    EFFECT_SOLID: SanmliTh05Code.SOLID_LIGHT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Th05ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the candle light."""
    if not (infrared_entity_id := entry.data.get(CONF_INFRARED_ENTITY_ID)):
        return
    async_add_entities([Th05Light(entry, infrared_entity_id)])


class Th05Light(Th05EmitterEntity, LightEntity):
    """The candle set as a light."""

    _attr_name = None
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [
        EFFECT_CANDLE,
        EFFECT_FLICKER,
        EFFECT_FADE_OUT,
        EFFECT_SOLID,
    ]

    def __init__(self, entry: Th05ConfigEntry, infrared_entity_id: str) -> None:
        """Initialize the light."""
        super().__init__(entry, "light", infrared_entity_id)
        self._attr_is_on: bool | None = None
        self._attr_effect: str | None = None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the candles on, optionally selecting an effect.

        An effect implies on, so sending both would send two codes where the
        remote sends one. When an effect is asked for, that code is the whole
        instruction.
        """
        if (effect := kwargs.get(ATTR_EFFECT)) in _EFFECT_TO_CODE:
            await self._async_send_code(_EFFECT_TO_CODE[effect])
            self._attr_effect = effect
        else:
            await self._async_send_code(SanmliTh05Code.ON)
        self._attr_is_on = True
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the candles off."""
        await self._async_send_code(SanmliTh05Code.OFF)
        self._attr_is_on = False
        self.async_write_ha_state()
