"""Climate platform: the Daikin FTXS50KVM as one assumed-state entity.

Every change sends one complete state, because that is what the Daikin
remote sends: mode, fan, swing and temperature travel together in one code.
The code is never built here. It is looked up in the lattice the wig
carries, one captured code per state, and replayed.

Infrared is one way. Nothing here can see whether the unit changed, and a
press on the handheld remote goes unheard, so the state shown is the last
state Home Assistant sent. The next change from Home Assistant sends the
whole state again, which puts the unit back in step.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Self, override

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.infrared import InfraredEmitterConsumerEntity
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from . import DaikinConfigEntry
from .command import CellCommand
from .const import (
    CONF_INFRARED_ENTITY_ID,
    CONF_SEND_COUNT,
    DEFAULT_SEND_COUNT,
    MAX_SEND_COUNT,
    MIN_SEND_COUNT,
    SEND_REPEAT_GAP,
)
from .entity import DaikinEntity
from .lattice import FAN_MODES, HVAC_MODES, SWING_MODES, Cell, ha_fan_mode

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    async_add_entities([DaikinClimate(entry, entry.data[CONF_INFRARED_ENTITY_ID])])


@dataclass
class _AssumedState(ExtraStoredData):
    """The state last sent, kept across restarts in the entity's own units.

    Not read back from the state machine's attributes: those are converted
    to the installation's unit system, so on an imperial install a restored
    target of 86 would be 86 degrees Celsius. Everything here is Celsius and
    the entity's own words.
    """

    hvac_mode: str | None
    last_on_mode: str | None
    fan_mode: str | None
    swing_mode: str | None
    temperature: float | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for the restore cache."""
        return {
            "hvac_mode": self.hvac_mode,
            "last_on_mode": self.last_on_mode,
            "fan_mode": self.fan_mode,
            "swing_mode": self.swing_mode,
            "temperature": self.temperature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Read back from the restore cache."""
        temperature = data.get("temperature")
        return cls(
            hvac_mode=data.get("hvac_mode"),
            last_on_mode=data.get("last_on_mode"),
            fan_mode=data.get("fan_mode"),
            swing_mode=data.get("swing_mode"),
            temperature=None if temperature is None else float(temperature),
        )


class DaikinClimate(
    DaikinEntity, InfraredEmitterConsumerEntity, ClimateEntity, RestoreEntity
):
    """The air conditioner, driven by replaying lattice codes."""

    _attr_name = None
    _attr_translation_key = "daikin_ac"
    _attr_assumed_state = True
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: DaikinConfigEntry, emitter_entity_id: str) -> None:
        """Initialize from the lattice the entry loaded."""
        super().__init__(entry, "climate")
        self._entry = entry
        self._infrared_emitter_entity_id = emitter_entity_id
        self._resolver = entry.runtime_data.resolver
        lattice = entry.runtime_data.lattice
        self._off_code = lattice.off

        # Offer only what the lattice can actually send.
        self._attr_hvac_modes = [HVACMode.OFF] + [
            HVACMode(ha_mode)
            for ha_mode, wig_mode in HVAC_MODES.items()
            if wig_mode in lattice.modes
        ]
        self._attr_fan_modes = [
            ha_fan for ha_fan, wig_fan in FAN_MODES.items()
            if wig_fan in lattice.fan_modes
        ]
        self._attr_swing_modes = [s for s in SWING_MODES if s in lattice.swing_modes]
        self._attr_min_temp = lattice.min_temp
        self._attr_max_temp = lattice.max_temp
        self._attr_target_temperature_step = lattice.precision

        # Start where the resolver lands with nothing asked for: the first
        # mode's first fan and swing, at the middle temperature.
        first_mode = self._attr_hvac_modes[1]
        start = self._resolver.resolve(first_mode, None, None, None)
        self._attr_hvac_mode = HVACMode.OFF
        self._last_on_mode: HVACMode = first_mode
        self._attr_fan_mode = ha_fan_mode(start.fan) if start else None
        self._attr_swing_mode = start.swing if start else None
        self._attr_target_temperature = start.temp if start else None

    @property
    def extra_restore_state_data(self) -> _AssumedState:
        """Remember what was last sent, and which mode Turn on returns to."""
        return _AssumedState(
            hvac_mode=self._attr_hvac_mode,
            last_on_mode=self._last_on_mode,
            fan_mode=self._attr_fan_mode,
            swing_mode=self._attr_swing_mode,
            temperature=self._attr_target_temperature,
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the assumed state, since infrared cannot read it back."""
        await super().async_added_to_hass()

        extra = await self.async_get_last_extra_data()
        if extra is None:
            return
        saved = _AssumedState.from_dict(extra.as_dict())
        if saved.hvac_mode in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(saved.hvac_mode)
        if saved.last_on_mode in self._attr_hvac_modes and (
            saved.last_on_mode != HVACMode.OFF
        ):
            self._last_on_mode = HVACMode(saved.last_on_mode)
        if saved.fan_mode in self._attr_fan_modes:
            self._attr_fan_mode = saved.fan_mode
        if saved.swing_mode in self._attr_swing_modes:
            self._attr_swing_mode = saved.swing_mode
        if saved.temperature is not None:
            self._attr_target_temperature = min(
                max(saved.temperature, self._attr_min_temp), self._attr_max_temp
            )

    @property
    def _send_count(self) -> int:
        """How many times one change transmits."""
        raw = self._entry.options.get(
            CONF_SEND_COUNT, self._entry.data.get(CONF_SEND_COUNT, DEFAULT_SEND_COUNT)
        )
        try:
            count = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_SEND_COUNT
        return max(MIN_SEND_COUNT, min(count, MAX_SEND_COUNT))

    async def _async_transmit(self, pronto: str) -> None:
        """Send one code, as many times as configured."""
        command = CellCommand(pronto)
        for attempt in range(self._send_count):
            if attempt:
                await asyncio.sleep(SEND_REPEAT_GAP)
            await self._send_command(command)

    async def _async_apply(
        self,
        hvac_mode: HVACMode,
        fan_mode: str | None,
        swing_mode: str | None,
        temperature: float | None,
    ) -> None:
        """Send a complete state, then show exactly what was sent.

        The state is only updated after the send returns. A send that raised
        reached nothing, and showing it anyway would be a claim about the room
        that is not true.
        """
        if hvac_mode == HVACMode.OFF:
            await self._async_transmit(self._off_code)
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            return

        cell: Cell | None = self._resolver.resolve(
            hvac_mode, fan_mode, swing_mode, temperature
        )
        if cell is None:
            raise HomeAssistantError(f"No code in the lattice for {hvac_mode}")
        await self._async_transmit(cell.pronto)

        # Show the cell that went out. The resolver snaps to what the lattice
        # has, so this is the state the unit was actually asked for.
        self._attr_hvac_mode = hvac_mode
        self._last_on_mode = hvac_mode
        self._attr_fan_mode = ha_fan_mode(cell.fan)
        self._attr_swing_mode = cell.swing
        self._attr_target_temperature = cell.temp
        self.async_write_ha_state()

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the mode, sending the rest of the state with it."""
        await self._async_apply(
            hvac_mode,
            self._attr_fan_mode,
            self._attr_swing_mode,
            self._attr_target_temperature,
        )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target, and the mode too when one is given."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode: HVACMode | None = kwargs.get(ATTR_HVAC_MODE)
        if hvac_mode is not None:
            self._valid_mode_or_raise("hvac", hvac_mode, self.hvac_modes)
        target = (
            float(temperature)
            if temperature is not None
            else self._attr_target_temperature
        )
        mode = hvac_mode or self._attr_hvac_mode or HVACMode.OFF
        if mode == HVACMode.OFF:
            # Nothing to send while off; the next Turn on sends it.
            if hvac_mode is not None:
                await self._async_apply(
                    HVACMode.OFF, self._attr_fan_mode, self._attr_swing_mode, target
                )
            self._attr_target_temperature = target
            self.async_write_ha_state()
            return
        await self._async_apply(
            mode, self._attr_fan_mode, self._attr_swing_mode, target
        )

    @override
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan, sending the whole state when the unit is on."""
        if self._attr_hvac_mode in (None, HVACMode.OFF):
            self._attr_fan_mode = fan_mode
            self.async_write_ha_state()
            return
        await self._async_apply(
            self._attr_hvac_mode,
            fan_mode,
            self._attr_swing_mode,
            self._attr_target_temperature,
        )

    @override
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the swing, sending the whole state when the unit is on."""
        if self._attr_hvac_mode in (None, HVACMode.OFF):
            self._attr_swing_mode = swing_mode
            self.async_write_ha_state()
            return
        await self._async_apply(
            self._attr_hvac_mode,
            self._attr_fan_mode,
            swing_mode,
            self._attr_target_temperature,
        )

    @override
    async def async_turn_on(self) -> None:
        """Turn on in the last mode used, with the current settings."""
        await self.async_set_hvac_mode(self._last_on_mode)

    @override
    async def async_turn_off(self) -> None:
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
