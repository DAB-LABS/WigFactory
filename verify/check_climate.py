"""Step 4 for a climate integration: the lattice, the resolver, the wire.

A codebook integration is checked by encoding every button and decoding it
back. A climate integration has no codebook. It ships the wig's lattice as
data and replays one captured code per state, so what can go wrong is
different, and so are the checks:

1. **The lattice is the wig's.** The integration's ``lattice.json`` must
   carry the wig's climate block unchanged, field for field. A lattice that
   drifted from the fitted one is sending codes nobody vouched for.
2. **The resolver agrees with HAIR on every state.** The integration vendors
   HAIR's ``resolve_cell``. Copies drift, and a resolver that drifts sends
   the wrong state to somebody's air conditioner, so this walks every state
   the entity offers, plus off-grid and out-of-range requests, and requires
   the same cell HAIR's resolver picks, every time.
3. **Every advertised state lands on itself, and every cell is reachable.**
   A control that snaps somewhere else does something other than it says; a
   cell nothing can reach is a state the user cannot select.
4. **The wire matches HAIR's.** Every cell, and Off, converts to exactly the
   timings HAIR itself would transmit, terminator included, and nothing in
   them overflows a 16-bit emitter.

The integration's ``lattice.py`` and ``command.py`` are imported directly.
They are written to import nothing from Home Assistant for exactly this
reason: the gate calls the same code the entity calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

# The longest single timing a 16-bit emitter format can carry.
UINT16_MAX_US = 65_535

# Home Assistant translation keys: lowercase, digits, underscore, hyphen.
_TRANSLATION_KEY = re.compile(r"^[a-z0-9_-]+$")

LATTICE_API = ("parse_lattice", "load_lattice", "Resolver", "FAN_MODES",
               "HVAC_MODES", "SWING_MODES")
COMMAND_API = ("CellCommand",)


def find_climate_component(root: Path) -> Path | None:
    """The component directory of a climate integration, if this is one."""
    for lattice in sorted(root.glob("custom_components/*/lattice.json")):
        if (lattice.parent / "lattice.py").is_file():
            return lattice.parent
    return None


def _cell_tuple(cell: Any) -> tuple[Any, ...] | None:
    if cell is None:
        return None
    temp = None if cell.temp is None else float(cell.temp)
    return (cell.mode, cell.fan, cell.swing, temp, cell.pronto)


def _temps(low: float, high: float, step: float) -> list[float]:
    count = round((high - low) / step)
    return [round(low + i * step, 4) for i in range(count + 1)]


def check_climate_integration(
    hair: Any,
    wig: Any,
    wig_path: Path,
    component: Path,
    load_module: Callable[[Path, str], Any],
    report: Any,
) -> None:
    """Run every climate check. Failures go to the report; nothing raises."""
    matrix = getattr(wig, "climate", None)
    if matrix is None:
        report.fail(
            f"{component.name} ships a lattice, but the wig has no climate "
            f"block to check it against"
        )
        return

    lattice_mod = _import(load_module, component / "lattice.py", LATTICE_API, report)
    command_mod = _import(load_module, component / "command.py", COMMAND_API, report)
    if lattice_mod is None:
        return

    ours = _check_lattice_file(lattice_mod, component, wig, wig_path, report)
    if ours is None:
        return
    _check_vocabulary(lattice_mod, matrix, component, report)
    _check_resolution(hair, lattice_mod, ours, matrix, report)
    if command_mod is not None:
        _check_wire(hair, command_mod, matrix, report)

    # The send count a lattice states lives on its cells. Hand it to the
    # shared send-count check the same way a codebook's recipe is.
    counts = sorted({int(getattr(c, "send_count", 1) or 1) for c in matrix.cells})
    recipe = report.facts.setdefault("recipe", {})
    if not recipe.get("derived"):
        recipe["derived"] = counts[-1]
        recipe["send_counts"] = counts


def _import(
    load_module: Callable[[Path, str], Any],
    path: Path,
    required: tuple[str, ...],
    report: Any,
) -> Any | None:
    if not path.is_file():
        report.fail(f"{path.name} is missing from {path.parent.name}")
        return None
    try:
        module = load_module(path, path.stem)
    except Exception as err:  # noqa: BLE001 - reported, and it is a refusal
        report.fail(f"{path.name} does not import without Home Assistant: {err!r}")
        return None
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        report.fail(f"{path.name} lacks {', '.join(missing)}")
        return None
    return module


def _check_lattice_file(
    lattice_mod: Any, component: Path, wig: Any, wig_path: Path, report: Any
) -> Any | None:
    """The shipped lattice is the wig's climate block, unchanged."""
    path = component / "lattice.json"
    try:
        shipped = json.loads(path.read_text(encoding="utf-8"))
        source = json.loads(wig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        report.fail(f"cannot read the lattice or the wig as JSON: {err!r}")
        return None

    if shipped.get("climate") != source.get("climate"):
        a, b = shipped.get("climate") or {}, source.get("climate") or {}
        differs = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        report.fail(
            f"lattice.json is not the wig's climate block: it differs in "
            f"{', '.join(differs) or 'shape'}. The integration would send codes "
            f"that are not the ones fitted."
        )
        return None
    shipped_id = (shipped.get("wig") or {}).get("wig_id")
    if shipped_id != getattr(wig, "wig_id", None):
        report.fail(
            f"lattice.json names wig {shipped_id}, but the wig is "
            f"{getattr(wig, 'wig_id', None)}"
        )
        return None

    try:
        ours = lattice_mod.load_lattice(path)
    except Exception as err:  # noqa: BLE001 - reported, and it is a refusal
        report.fail(f"the integration cannot load its own lattice: {err!r}")
        return None
    report.ok(
        f"lattice.json is the wig's climate block, unchanged: "
        f"{len(ours.cells)} cells and Off"
    )
    return ours


def _check_vocabulary(
    lattice_mod: Any, matrix: Any, component: Path, report: Any
) -> None:
    """Every word the entity offers maps onto the wig, one to one."""
    fan_map: dict[str, str] = dict(lattice_mod.FAN_MODES)
    mode_map: dict[str, str] = dict(lattice_mod.HVAC_MODES)
    swings = tuple(lattice_mod.SWING_MODES)

    wig_fans = set(matrix.fan_modes) | {c.fan for c in matrix.cells if c.fan}
    wig_modes = set(matrix.modes) | {c.mode for c in matrix.cells}
    wig_swings = set(matrix.swing_modes) | {c.swing for c in matrix.cells if c.swing}

    problems = []
    if len(set(fan_map.values())) != len(fan_map):
        problems.append("two fan words map to one wig fan")
    if set(fan_map.values()) != wig_fans:
        problems.append(
            f"fan words cover {sorted(set(fan_map.values()))}, the wig has "
            f"{sorted(wig_fans)}"
        )
    if len(set(mode_map.values())) != len(mode_map):
        problems.append("two modes map to one wig mode")
    if set(mode_map.values()) != wig_modes:
        problems.append(
            f"modes cover {sorted(set(mode_map.values()))}, the wig has "
            f"{sorted(wig_modes)}"
        )
    if not wig_swings <= set(swings):
        problems.append(
            f"swing words {list(swings)} miss the wig's {sorted(wig_swings)}"
        )
    # Which Home Assistant word names which wig speed is a judgment, and the
    # gate cannot check the judgment. It can check the order: the entity
    # offers speeds slowest first, and so does the wig, so a swapped pair
    # shows up as the two lists disagreeing.
    declared = [f for f in matrix.fan_modes if f in wig_fans]
    if declared and list(fan_map.values()) != declared:
        problems.append(
            f"fan words run {list(fan_map.values())}, the wig orders its "
            f"speeds {declared}"
        )
    bad_keys = [k for k in fan_map if not _TRANSLATION_KEY.match(k)]
    if bad_keys:
        problems.append(f"fan words that cannot be translation keys: {bad_keys}")

    translated = _fan_translations(component)
    if translated is not None:
        untranslated = [k for k in fan_map if k not in translated]
        if untranslated:
            problems.append(f"fan words with no English name: {untranslated}")

    if problems:
        for problem in problems:
            report.fail(f"entity vocabulary: {problem}")
        return
    pairs = ", ".join(f"{k} = {v}" for k, v in fan_map.items())
    report.ok(f"every mode, fan and swing maps one to one onto the wig ({pairs})")


def _fan_translations(component: Path) -> set[str] | None:
    path = component / "translations" / "en.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    found: set[str] = set()
    for entity in (data.get("entity") or {}).get("climate", {}).values():
        states = ((entity.get("state_attributes") or {}).get("fan_mode") or {}).get(
            "state"
        ) or {}
        found |= set(states)
    return found


def _wig_offers(matrix: Any) -> dict[str, dict[str, list[Any]]]:
    """What each mode of the wig actually carries: its fans, swings, temps.

    Declared vocabulary order first, then anything observed and undeclared,
    the same ordering HAIR's resolver uses.
    """
    def ordered(declared: list[Any], seen: list[Any]) -> list[Any]:
        out = [v for v in declared if v in seen]
        return out + [v for v in seen if v not in out]

    by_mode: dict[str, list[Any]] = {}
    for cell in matrix.cells:
        by_mode.setdefault(cell.mode, []).append(cell)
    offers: dict[str, dict[str, list[Any]]] = {}
    for mode, cells in by_mode.items():
        fans = list(dict.fromkeys(c.fan for c in cells if c.fan is not None))
        swings = list(dict.fromkeys(c.swing for c in cells if c.swing is not None))
        offers[mode] = {
            "fans": ordered(list(matrix.fan_modes), fans),
            "swings": ordered(list(matrix.swing_modes), swings),
            "temps": sorted({float(c.temp) for c in cells if c.temp is not None}),
        }
    return offers


def _check_offers(
    resolver: Any,
    mode_map: dict[str, str],
    fan_map: dict[str, str],
    wig: dict[str, dict[str, list[Any]]],
    report: Any,
) -> dict[str, dict[str, list[Any]]] | None:
    """The integration's own statement of what each mode offers, checked.

    Needed only when modes differ. Returns, per Home Assistant mode, the
    states the entity offers in the wig's words, or None when the
    integration does not say and has to.
    """
    per_mode = len({
        (tuple(o["fans"]), tuple(o["swings"]), tuple(o["temps"]))
        for o in wig.values()
    }) > 1
    offers_fn = getattr(resolver, "offers", None)
    if offers_fn is None:
        if per_mode:
            report.fail(
                "the wig's modes offer different settings (for example a dry "
                "mode with one fan speed), and lattice.py does not say what "
                "each mode offers. Add Resolver.offers(hvac_mode) and have "
                "the entity show only those, or Home Assistant will offer "
                "settings that do nothing."
            )
            return None
        return {
            ha: {"fans": wig[w]["fans"], "swings": wig[w]["swings"],
                 "temps": wig[w]["temps"]}
            for ha, w in mode_map.items() if w in wig
        }

    stated: dict[str, dict[str, list[Any]]] = {}
    wrong: list[str] = []
    for ha_mode, wig_mode in mode_map.items():
        try:
            raw = offers_fn(ha_mode)
            fans = [fan_map.get(f, f) for f in raw["fan_modes"]]
            swings = list(raw["swing_modes"])
            temps = [float(x) for x in raw["temperatures"]]
        except Exception as err:  # noqa: BLE001 - reported, and it is a refusal
            wrong.append(f"{ha_mode} ({err!r})")
            continue
        want = wig.get(wig_mode)
        if want is None or (fans, swings, temps) != (
            want["fans"], want["swings"], want["temps"]
        ):
            wrong.append(ha_mode)
        stated[ha_mode] = {"fans": fans, "swings": swings, "temps": temps}
    if wrong:
        report.fail(
            f"Resolver.offers disagrees with what the wig carries for "
            f"{', '.join(wrong)}. The entity must offer exactly the settings "
            f"each mode has: no fewer, no more."
        )
        return None
    report.ok(
        "Resolver.offers matches the wig mode by mode: "
        + "; ".join(
            f"{m} {len(o['fans']) or 1} fan x {len(o['swings']) or 1} swing x "
            f"{len(o['temps']) or 1} temp"
            for m, o in stated.items()
        )
    )
    return stated


def _check_resolution(
    hair: Any, lattice_mod: Any, ours: Any, matrix: Any, report: Any
) -> None:
    """Every state resolves exactly as HAIR resolves it.

    Two walks over one set of requests. Agreement: every request, offered or
    not, including off-grid and out-of-range temperatures, must resolve to
    the cell HAIR's resolver picks. Landing: every state the entity offers,
    mode by mode, must resolve to exactly itself, and together they must
    reach every cell.
    """
    resolve_hair = hair.wig_climate.resolve_cell
    resolver = lattice_mod.Resolver(ours)
    fan_map: dict[str, str] = dict(lattice_mod.FAN_MODES)
    mode_map: dict[str, str] = dict(lattice_mod.HVAC_MODES)
    swings = [s for s in lattice_mod.SWING_MODES if s in set(matrix.swing_modes)]
    wig_to_ha_fan = {w: h for h, w in fan_map.items()}

    offered = _check_offers(resolver, mode_map, fan_map, _wig_offers(matrix), report)

    grid = _temps(float(matrix.min_temp), float(matrix.max_temp),
                  float(matrix.precision or 1))
    middle = grid[len(grid) // 2]
    odd_temps = [grid[0] - 1, grid[-1] + 1, middle + 0.4, middle - 0.6, None]

    walked = 0
    disagreements: list[str] = []
    for ha_mode, wig_mode in mode_map.items():
        for ha_fan in [*fan_map, None]:
            wig_fan = fan_map.get(ha_fan) if ha_fan is not None else None
            for swing in [*swings, None]:
                for temp in [*grid, *odd_temps]:
                    walked += 1
                    got = _cell_tuple(resolver.resolve(ha_mode, ha_fan, swing, temp))
                    want = _cell_tuple(
                        resolve_hair(matrix, wig_mode, wig_fan, swing, temp)
                    )
                    if got != want:
                        disagreements.append(f"{ha_mode}/{ha_fan}/{swing}/{temp}")

    snapped: list[str] = []
    reached: set[tuple[Any, ...]] = set()
    for ha_mode, offer in (offered or {}).items():
        wig_mode = mode_map[ha_mode]
        for wig_fan in offer["fans"] or [None]:
            ha_fan = wig_to_ha_fan.get(wig_fan) if wig_fan is not None else None
            for swing in offer["swings"] or [None]:
                for temp in offer["temps"] or [None]:
                    got = _cell_tuple(resolver.resolve(ha_mode, ha_fan, swing, temp))
                    label = f"{ha_mode}/{ha_fan}/{swing}/{temp}"
                    if got is None:
                        snapped.append(f"{label} (nothing)")
                        continue
                    reached.add(got)
                    expect_temp = None if temp is None else float(temp)
                    if got[:4] != (wig_mode, wig_fan, swing, expect_temp):
                        snapped.append(label)

    all_cells = {_cell_tuple(c) for c in matrix.cells}
    unreached = all_cells - reached if offered is not None else set()
    report.facts["climate_integration"] = {
        "states_walked": walked,
        "cells": len(all_cells),
        "cells_reached": len(reached & all_cells),
        "per_mode": offered is not None and any(
            o != next(iter(offered.values())) for o in offered.values()
        ),
        "resolver": getattr(lattice_mod, "RESOLVER_SOURCE", None),
    }

    if disagreements:
        report.fail(
            f"the integration's resolver and HAIR's disagree on "
            f"{len(disagreements)} of {walked} requests, first "
            f"{', '.join(disagreements[:4])}. One of them sends the wrong state."
        )
    if snapped:
        report.fail(
            f"{len(snapped)} offered state(s) do not land on themselves, "
            f"first {', '.join(snapped[:4])}. That is a control that does "
            f"something other than it says."
        )
    if unreached:
        report.fail(
            f"{len(unreached)} cell(s) cannot be reached from any offered "
            f"state, so the user can never select them"
        )
    if offered is not None and not (disagreements or snapped or unreached):
        report.ok(
            f"resolver agrees with HAIR's on all {walked} requests walked, "
            f"every offered state lands on itself, and all "
            f"{len(all_cells)} cells are reachable"
        )


def _check_wire(hair: Any, command_mod: Any, matrix: Any, report: Any) -> None:
    """Every code goes out exactly as HAIR would send it."""
    ir = hair.ir_command
    codes = [("Off", matrix.off)] + [
        (hair.cell_key(c), c.pronto) for c in matrix.cells
    ]
    wrong: list[str] = []
    unterminated: list[str] = []
    overflow: list[str] = []
    for label, pronto in codes:
        try:
            ours = command_mod.CellCommand(pronto)
            ours_t = list(ours.get_raw_timings())
        except Exception as err:  # noqa: BLE001 - reported, and it is a refusal
            wrong.append(f"{label} ({err!r})")
            continue
        theirs = ir.TerminatedCommand(ir.ProntoCommand(pronto))
        if ours_t != list(theirs.get_raw_timings()) or (
            ours.modulation != theirs.modulation
        ):
            wrong.append(label)
        if not ours_t or ours_t[-1] != -ir.TERMINATOR_SPACE_US:
            unterminated.append(label)
        if any(abs(v) > UINT16_MAX_US for v in ours_t):
            overflow.append(label)

    if wrong:
        report.fail(
            f"{len(wrong)} code(s) do not convert to the timings HAIR sends, "
            f"first {', '.join(wrong[:4])}"
        )
    if unterminated:
        report.fail(
            f"{len(unterminated)} code(s) do not end on the "
            f"{ir.TERMINATOR_SPACE_US // 1000} ms terminator, which Broadlink "
            f"RM4 Pro firmware needs"
        )
    if overflow:
        report.fail(
            f"{len(overflow)} code(s) carry a timing over {UINT16_MAX_US} us, "
            f"which 16-bit emitters reject"
        )
    if not (wrong or unterminated or overflow):
        report.ok(
            f"all {len(codes)} codes convert to exactly HAIR's transmit "
            f"timings, end on the {ir.TERMINATOR_SPACE_US // 1000} ms "
            f"terminator, and fit a 16-bit emitter"
        )
