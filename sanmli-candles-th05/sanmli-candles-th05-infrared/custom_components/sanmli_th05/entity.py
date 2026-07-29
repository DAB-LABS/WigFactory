"""Common entity bases for the Sanmli TH-05 candle integration."""

from __future__ import annotations

from homeassistant.components.infrared import InfraredEmitterConsumerEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import Th05ConfigEntry
from .codes import SanmliTh05Code
from .const import DEVICE_NAME, DOMAIN, MANUFACTURER, MODEL


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

    async def _async_send_code(self, code: SanmliTh05Code) -> None:
        """Send one codebook entry, then advance the entry's RC-5 toggle."""
        data = self._entry.runtime_data
        await self._send_command(code.to_command(toggle=data.toggle))
        data.advance()
