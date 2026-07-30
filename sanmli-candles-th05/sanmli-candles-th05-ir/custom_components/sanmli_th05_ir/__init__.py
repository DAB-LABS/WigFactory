"""Sanmli TH-05 LED candle integration."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.BUTTON, Platform.EVENT, Platform.LIGHT]

type Th05ConfigEntry = ConfigEntry[Th05RuntimeData]


@dataclass
class Th05RuntimeData:
    """State shared by every entity in one config entry.

    Only the RC-5 toggle so far. It has to be shared: the toggle tells the
    candle whether a signal is a new press or a repeat of the last one, and it
    is a property of the conversation with the device rather than of any one
    button. A per-entity toggle would make two presses of different buttons
    look like one held key.
    """

    _toggle: int = field(default=0)

    @property
    def toggle(self) -> int:
        """The toggle value to send with the next command."""
        return self._toggle

    def advance(self) -> None:
        """Flip the toggle after a command has actually gone out.

        Advanced on success only. A send that failed everywhere never reached
        the candle, so the next attempt should carry the same toggle rather
        than looking to the device like a different press.
        """
        self._toggle ^= 1


async def async_setup_entry(hass: HomeAssistant, entry: Th05ConfigEntry) -> bool:
    """Set up the candle integration from a config entry."""
    entry.runtime_data = Th05RuntimeData()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Th05ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
