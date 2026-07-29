"""Button platform: one button per captured signal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Th05ConfigEntry
from .codes import SanmliTh05Code
from .const import CONF_INFRARED_ENTITY_ID
from .entity import Th05EmitterEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Th05ButtonEntityDescription(ButtonEntityDescription):
    """Describes a candle button."""

    command_code: SanmliTh05Code


# One per signal in the wig, in the order they sit on the physical remote.
# The whole remote is here on purpose, including On and Off, so an automation
# can reach any code the light and its effects do not expose.
BUTTON_DESCRIPTIONS: tuple[Th05ButtonEntityDescription, ...] = (
    Th05ButtonEntityDescription(
        key="on", translation_key="on", command_code=SanmliTh05Code.ON
    ),
    Th05ButtonEntityDescription(
        key="off", translation_key="off", command_code=SanmliTh05Code.OFF
    ),
    Th05ButtonEntityDescription(
        key="brighten", translation_key="brighten",
        command_code=SanmliTh05Code.BRIGHTEN,
    ),
    Th05ButtonEntityDescription(
        key="dim", translation_key="dim", command_code=SanmliTh05Code.DIM
    ),
    Th05ButtonEntityDescription(
        key="candle_like", translation_key="candle_like",
        command_code=SanmliTh05Code.CANDLE_LIKE,
    ),
    Th05ButtonEntityDescription(
        key="flicker", translation_key="flicker",
        command_code=SanmliTh05Code.FLICKER,
    ),
    Th05ButtonEntityDescription(
        key="fade_out", translation_key="fade_out",
        command_code=SanmliTh05Code.FADE_OUT,
    ),
    Th05ButtonEntityDescription(
        key="solid_light", translation_key="solid_light",
        command_code=SanmliTh05Code.SOLID_LIGHT,
    ),
    Th05ButtonEntityDescription(
        key="timer_2h", translation_key="timer_2h",
        command_code=SanmliTh05Code.TIMER_2H,
    ),
    Th05ButtonEntityDescription(
        key="timer_4h", translation_key="timer_4h",
        command_code=SanmliTh05Code.TIMER_4H,
    ),
    Th05ButtonEntityDescription(
        key="timer_6h", translation_key="timer_6h",
        command_code=SanmliTh05Code.TIMER_6H,
    ),
    Th05ButtonEntityDescription(
        key="timer_8h", translation_key="timer_8h",
        command_code=SanmliTh05Code.TIMER_8H,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Th05ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the candle buttons."""
    if not (infrared_entity_id := entry.data.get(CONF_INFRARED_ENTITY_ID)):
        return
    async_add_entities(
        Th05Button(entry, infrared_entity_id, description)
        for description in BUTTON_DESCRIPTIONS
    )


class Th05Button(Th05EmitterEntity, ButtonEntity):
    """A single candle command."""

    entity_description: Th05ButtonEntityDescription

    def __init__(
        self,
        entry: Th05ConfigEntry,
        infrared_entity_id: str,
        description: Th05ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, description.key, infrared_entity_id)
        self.entity_description = description

    @override
    async def async_press(self) -> None:
        """Send this button's command."""
        await self._async_send_code(self.entity_description.command_code)
