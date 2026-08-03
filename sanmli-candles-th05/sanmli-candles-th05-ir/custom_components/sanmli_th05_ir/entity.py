"""Common entity bases for the Sanmli TH-05 candle integration."""

from __future__ import annotations

import asyncio

from homeassistant.components.infrared import InfraredEmitterConsumerEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import Th05ConfigEntry
from .codes import WIG_DITTO_COUNT, SanmliTh05Code
from .const import (
    CONF_SEND_COUNT,
    DEFAULT_SEND_COUNT,
    DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
    MAX_SEND_COUNT,
    MIN_SEND_COUNT,
    MODEL,
    SEND_REPEAT_GAP,
)


class Th05Entity(Entity):
    """Base entity carrying the shared device info."""

    _attr_has_entity_name = True

    def __init__(self, entry: Th05ConfigEntry, unique_id_suffix: str) -> None:
        """Initialize the entity."""
        # Keyed on the entry id, never on the infrared entity_id. An entity_id
        # is renameable and a unique_id is forever; lg_infrared shipped that
        # mistake once and had to walk it back with a migration.
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )


class Th05EmitterEntity(Th05Entity, InfraredEmitterConsumerEntity):
    """Base for entities that transmit, with the shared RC-5 toggle."""

    def __init__(
        self,
        entry: Th05ConfigEntry,
        unique_id_suffix: str,
        infrared_entity_id: str,
    ) -> None:
        """Initialize the transmitting entity."""
        super().__init__(entry, unique_id_suffix)
        self._entry = entry
        self._infrared_emitter_entity_id = infrared_entity_id

    @property
    def _send_count(self) -> int:
        """How many frames one press transmits."""
        raw = self._entry.options.get(
            CONF_SEND_COUNT, self._entry.data.get(CONF_SEND_COUNT, DEFAULT_SEND_COUNT)
        )
        try:
            count = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_SEND_COUNT
        return max(MIN_SEND_COUNT, min(count, MAX_SEND_COUNT))

    async def _async_send_code(self, code: SanmliTh05Code) -> None:
        """Send one codebook entry as one press, then advance the toggle.

        Two different repeats are at work here and they are not
        interchangeable.

        `repeat_count` is the DITTO: repeat frames the encoder renders inside
        a single transmission, back to back at the protocol's own timing. It
        comes from the wig, it is part of the waveform, and it is inside the
        row digest a fitter signed. It is not tunable, because changing it
        would mean transmitting something nobody attested.

        `_send_count` is DELIVERY: the whole transmission sent again after a
        pause, because a receiver on a duty cycle can sleep through one. It is
        the user's to change, and it sits outside the digest on purpose --
        how many times to press depends on the room, not on the device.

        Every frame in the press carries the SAME toggle. That is what makes
        it one press repeated rather than several presses: the toggle is how
        the candle tells a held key from a new one, so flipping it between
        frames would turn a single Dim into three steps.

        The toggle advances once, afterwards, and only if the send did not
        raise. A press that reached nothing should not consume a toggle value,
        because the candle never saw it.
        """
        data = self._entry.runtime_data
        command = code.to_command(
            toggle=data.toggle, repeat_count=WIG_DITTO_COUNT
        )
        for frame in range(self._send_count):
            if frame:
                await asyncio.sleep(SEND_REPEAT_GAP)
            await self._send_command(command)
        data.advance()
