"""Common entity base for the Daikin FTXS50KVM integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DaikinConfigEntry
from .const import DEVICE_NAME, DOMAIN, MANUFACTURER, MODEL


class DaikinEntity(Entity):
    """Base entity carrying the shared device info."""

    _attr_has_entity_name = True

    def __init__(self, entry: DaikinConfigEntry, unique_id_suffix: str) -> None:
        """Initialize the entity."""
        # Keyed on the entry id, never on the infrared entity_id. An entity_id
        # is renameable and a unique_id is forever.
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
