"""The Daikin FTXS50KVM lattice, and how a requested state picks a cell.

An air conditioner remote does not send buttons. Every press sends the whole
state: mode, fan, swing and temperature in one frame. The wig this was built
from carries one captured code per state, 520 of them plus Off, and those
codes ship unchanged in ``lattice.json`` beside this file. Nothing here
encodes a Daikin frame; the integration only ever replays a code that was
captured off the real remote.

This module loads that file and resolves a Home Assistant state to exactly
one cell. It imports nothing from Home Assistant, so WigFactory's gate can
import it and walk every state the entity offers against HAIR's own resolver.

``resolve_cell`` and ``_Branches`` are vendored from HAIR 0.16.0,
``custom_components/hair/wig_climate.py``, trimmed to the lookup alone. Two
implementations of one lookup drift, and a resolver that drifts sends the
wrong state to somebody's air conditioner, so the gate proves this copy and
HAIR's agree on every state before anything is published.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

LATTICE_FILE = Path(__file__).with_name("lattice.json")
LATTICE_FORMAT = "hair-matrix/1"
RESOLVER_SOURCE = "HAIR 0.16.0 wig_climate.resolve_cell"

# Home Assistant's fan mode words, in the order the entity offers them, and
# the wig's own word for each. The wig's words are lookup keys and stay
# verbatim; Home Assistant's are what a user sees, and translation keys
# cannot carry a "+". The last two are core's own spelling (lg_infrared uses
# the same pair).
FAN_MODES: dict[str, str] = {
    "low": "low",
    "medium_low": "low+1",
    "medium": "mid",
    "medium_high": "mid+1",
    "high": "high",
}

# Home Assistant HVAC mode to the wig's mode key. Off is not a cell: it is a
# code of its own, sent on its own.
HVAC_MODES: dict[str, str] = {
    "cool": "cool",
    "heat": "heat",
}

# Swing words are identical in the wig and in Home Assistant's climate
# constants (SWING_OFF, SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH).
SWING_MODES: tuple[str, ...] = ("off", "vertical", "horizontal", "both")


class LatticeError(ValueError):
    """The lattice file is missing, malformed, or not the one expected."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One complete device state and the code that sets it."""

    mode: str
    fan: str | None
    swing: str | None
    temp: float | None
    pronto: str
    send_count: int = 1


@dataclass(frozen=True, slots=True)
class Lattice:
    """The whole climate block, as the wig states it."""

    min_temp: float
    max_temp: float
    precision: float
    unit: str
    modes: tuple[str, ...]
    fan_modes: tuple[str, ...]
    swing_modes: tuple[str, ...]
    off: str
    cells: tuple[Cell, ...]
    wig_id: str | None = None


def _cell(raw: dict[str, Any]) -> Cell:
    temp = raw.get("temp")
    return Cell(
        mode=str(raw["mode"]),
        fan=None if raw.get("fan") is None else str(raw["fan"]),
        swing=None if raw.get("swing") is None else str(raw["swing"]),
        temp=None if temp is None else float(temp),
        pronto=str(raw["pronto"]),
        send_count=int(raw.get("send_count", 1)),
    )


def parse_lattice(data: dict[str, Any]) -> Lattice:
    """Build a lattice from the file's JSON, refusing anything unexpected."""
    if data.get("format") != LATTICE_FORMAT:
        raise LatticeError(f"not a {LATTICE_FORMAT} file: {data.get('format')!r}")
    climate = data.get("climate")
    if not isinstance(climate, dict):
        raise LatticeError("no climate block")
    unit = str(climate.get("unit", "C"))
    if unit != "C":
        # A Fahrenheit lattice read as Celsius is a silent thirty degree error.
        raise LatticeError(f"lattice is in {unit}, this integration speaks Celsius")
    try:
        cells = tuple(_cell(raw) for raw in climate["cells"])
        lattice = Lattice(
            min_temp=float(climate["min_temp"]),
            max_temp=float(climate["max_temp"]),
            precision=float(climate.get("precision", 1)),
            unit=unit,
            modes=tuple(climate.get("modes", ())),
            fan_modes=tuple(climate.get("fan_modes", ())),
            swing_modes=tuple(climate.get("swing_modes", ())),
            off=str(climate["off"]),
            cells=cells,
            wig_id=(data.get("wig") or {}).get("wig_id"),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise LatticeError(f"malformed lattice: {err!r}") from err
    if not lattice.cells:
        raise LatticeError("lattice has no cells")
    return lattice


def load_lattice(path: Path = LATTICE_FILE) -> Lattice:
    """Read and parse the lattice file. Blocking: run it in the executor."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise LatticeError(f"cannot read {path.name}: {err!r}") from err
    return parse_lattice(data)


class _Branches:
    """Cells indexed mode -> fan -> swing -> sorted temps. Vendored."""

    def __init__(self, lattice: Lattice) -> None:
        self.lattice = lattice
        self.by_mode: dict[str, list[Cell]] = {}
        self.index: dict[
            tuple[str, str | None, str | None], dict[float | None, Cell]
        ] = {}
        for cell in lattice.cells:
            self.by_mode.setdefault(cell.mode, []).append(cell)
            self.index.setdefault((cell.mode, cell.fan, cell.swing), {})[
                cell.temp
            ] = cell

    def fans(self, mode: str) -> list[str]:
        observed: list[str] = []
        for cell in self.by_mode.get(mode, []):
            if cell.fan is not None and cell.fan not in observed:
                observed.append(cell.fan)
        ordered = [f for f in self.lattice.fan_modes if f in observed]
        ordered += [f for f in observed if f not in ordered]
        return ordered

    def swings(self, mode: str, fan: str | None) -> list[str]:
        observed: list[str] = []
        for cell in self.by_mode.get(mode, []):
            if (
                cell.fan == fan
                and cell.swing is not None
                and cell.swing not in observed
            ):
                observed.append(cell.swing)
        ordered = [s for s in self.lattice.swing_modes if s in observed]
        ordered += [s for s in observed if s not in ordered]
        return ordered

    def temps(self, mode: str, fan: str | None, swing: str | None) -> list[float]:
        branch = self.index.get((mode, fan, swing), {})
        return sorted(t for t in branch if t is not None)

    def cell(
        self, mode: str, fan: str | None, swing: str | None, temp: float | None
    ) -> Cell | None:
        return self.index.get((mode, fan, swing), {}).get(temp)


def resolve_cell(
    lattice: Lattice,
    mode: str,
    fan: str | None = None,
    swing: str | None = None,
    temp: float | None = None,
    *,
    branches: _Branches | None = None,
) -> Cell | None:
    """Return the cell nearest the requested state. Vendored from HAIR.

    Mode must match a real subtree. Fan and swing fall back to the branch's
    first value when the requested one does not exist there; temp snaps to
    the nearest available in the final branch. Returns None only when the
    mode has no cells at all.
    """
    branches = branches or _Branches(lattice)
    if mode not in branches.by_mode:
        return None
    fans = branches.fans(mode)
    use_fan = fan if fan in fans else (fans[0] if fans else None)
    swings = branches.swings(mode, use_fan)
    use_swing = swing if swing in swings else (swings[0] if swings else None)
    temps = branches.temps(mode, use_fan, use_swing)
    if not temps:
        return branches.cell(mode, use_fan, use_swing, None)
    target = (
        temps[len(temps) // 2]
        if temp is None
        else min(temps, key=lambda t: abs(t - temp))
    )
    return branches.cell(mode, use_fan, use_swing, target)


class Resolver:
    """The entity's one path from a Home Assistant state to a cell.

    Everything the climate entity sends goes through ``resolve``, and the
    gate calls exactly this, so what was checked is what runs.
    """

    def __init__(self, lattice: Lattice) -> None:
        """Index the lattice once, for every lookup after."""
        self.lattice = lattice
        self._branches = _Branches(lattice)

    def resolve(
        self,
        hvac_mode: str,
        fan_mode: str | None,
        swing_mode: str | None,
        temperature: float | None,
    ) -> Cell | None:
        """Resolve a Home Assistant state, or None when the mode has no cells."""
        mode = HVAC_MODES.get(hvac_mode)
        if mode is None:
            return None
        fan = FAN_MODES.get(fan_mode) if fan_mode is not None else None
        return resolve_cell(
            self.lattice, mode, fan, swing_mode, temperature,
            branches=self._branches,
        )


def ha_fan_mode(wig_fan: str | None) -> str | None:
    """Return the Home Assistant fan word for a wig fan key."""
    for ha_word, wig_word in FAN_MODES.items():
        if wig_word == wig_fan:
            return ha_word
    return None
