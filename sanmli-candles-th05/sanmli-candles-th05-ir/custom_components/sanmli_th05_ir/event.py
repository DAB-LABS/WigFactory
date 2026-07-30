"""Event platform: fires when the physical candle remote is used."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.components.event import EventEntity
from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    InfraredReceiverConsumerEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Th05ConfigEntry
from .codes import ADDRESS, SanmliTh05Code
from .const import CONF_INFRARED_RECEIVER_ENTITY_ID
from .decoder import RC5Command
from .entity import Th05Entity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_CODE_TO_EVENT_TYPE: dict[SanmliTh05Code, str] = {
    SanmliTh05Code.ON: "on",
    SanmliTh05Code.OFF: "off",
    SanmliTh05Code.BRIGHTEN: "brighten",
    SanmliTh05Code.DIM: "dim",
    SanmliTh05Code.CANDLE_LIKE: "candle_like",
    SanmliTh05Code.FLICKER: "flicker",
    SanmliTh05Code.FADE_OUT: "fade_out",
    SanmliTh05Code.SOLID_LIGHT: "solid_light",
    SanmliTh05Code.TIMER_2H: "timer_2h",
    SanmliTh05Code.TIMER_4H: "timer_4h",
    SanmliTh05Code.TIMER_6H: "timer_6h",
    SanmliTh05Code.TIMER_8H: "timer_8h",
}
_EVENT_TYPE_UNKNOWN = "unknown"
_EVENT_TYPES: list[str] = [*_CODE_TO_EVENT_TYPE.values(), _EVENT_TYPE_UNKNOWN]


def _flatten_timings(timings: Any) -> list[int] | None:
    """Coerce a received signal's timings to signed microsecond integers.

    The platform hands over a flat list today. It handed over Timing objects
    with `high_us` and `low_us` before, and that change broke an integration
    that assumed one shape (home-assistant/core#172209). Tolerating both costs
    a few lines and means a future migration cannot silently stop this entity
    from hearing the remote.
    """
    if not timings:
        return None
    flat: list[int] = []
    for entry in timings:
        if isinstance(entry, int):
            flat.append(entry)
            continue
        high = getattr(entry, "high_us", None)
        low = getattr(entry, "low_us", None)
        if high is None or low is None:
            return None
        flat.append(int(high))
        flat.append(-int(low))
    return flat or None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Th05ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the received-command event entity."""
    if not (receiver_entity_id := entry.data.get(CONF_INFRARED_RECEIVER_ENTITY_ID)):
        return
    async_add_entities([Th05ReceivedCommandEvent(entry, receiver_entity_id)])


class Th05ReceivedCommandEvent(
    Th05Entity, InfraredReceiverConsumerEntity, EventEntity
):
    """Fires when a Sanmli TH-05 command is heard on the receiver."""

    _attr_translation_key = "received_command"
    _attr_event_types = _EVENT_TYPES

    def __init__(self, entry: Th05ConfigEntry, receiver_entity_id: str) -> None:
        """Initialize the event entity."""
        super().__init__(entry, "received_command")
        self._infrared_receiver_entity_id = receiver_entity_id

    @callback
    @override
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Decode a received signal and fire the matching event."""
        timings = _flatten_timings(signal.timings)
        if timings is None:
            return

        command = RC5Command.from_raw_timings(timings)
        if command is None:
            return

        # Another RC-5 remote in the room is not this candle set.
        if command.address != ADDRESS:
            return

        try:
            code = SanmliTh05Code(command.command)
        except ValueError:
            # An address match with a command outside the codebook. Report it
            # rather than dropping it: growing the enum must never be able to
            # break this entity, and a silent drop hides a real signal.
            event_type = _EVENT_TYPE_UNKNOWN
        else:
            event_type = _CODE_TO_EVENT_TYPE.get(code, _EVENT_TYPE_UNKNOWN)

        _LOGGER.debug(
            "Received Sanmli TH-05 command: %s (0x%02X)", event_type, command.command
        )

        self._trigger_event(event_type)
        self.async_write_ha_state()
