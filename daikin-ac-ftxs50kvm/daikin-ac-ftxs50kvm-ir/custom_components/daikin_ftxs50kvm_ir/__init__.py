"""Daikin FTXS50KVM air conditioner, controlled over infrared."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .lattice import Lattice, LatticeError, Resolver, load_lattice

PLATFORMS = [Platform.CLIMATE]

type DaikinConfigEntry = ConfigEntry[DaikinRuntimeData]


@dataclass
class DaikinRuntimeData:
    """The lattice and its resolver, loaded once per config entry."""

    lattice: Lattice
    resolver: Resolver


async def async_setup_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Load the lattice off the event loop, then set up the climate entity."""
    try:
        lattice = await hass.async_add_executor_job(load_lattice)
    except LatticeError as err:
        # The lattice ships inside the integration, so this is a broken
        # install rather than something a retry would fix.
        raise ConfigEntryError(f"The code lattice could not be loaded: {err}") from err
    entry.runtime_data = DaikinRuntimeData(lattice=lattice, resolver=Resolver(lattice))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
