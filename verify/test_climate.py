#!/usr/bin/env python3
"""Behaviour tests for the climate integration checks in check_climate.py.

A climate integration ships the wig's lattice as data and replays one code
per state. These scenarios build a small climate integration in a temporary
directory, from the frozen integration modules in verify/fixtures/climate/
and a synthetic lattice, then break it one way at a time and require the
gate to say so:

- a clean build passes every check
- a lattice that is not the wig's refuses
- a resolver that drifts from HAIR's refuses
- fan words in the wrong order refuse
- a fan word with no English name refuses
- a code sent without the terminator refuses
- a Fahrenheit lattice refuses
- a lattice whose modes differ needs Resolver.offers, and offers must match

    .venv/bin/python verify/test_climate.py
    .venv/bin/python verify/test_climate.py --hair /path/to/HAIR

Exit 0 means every scenario behaved as expected.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import itertools
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_climate import check_climate_integration  # noqa: E402
from verify_wig import DEFAULT_HAIR, Hair, Report  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MODULES = FIXTURES / "climate"
CANDLE = FIXTURES / "sanmli-candles-th05.wig.json"

FANS = ["low", "low+1", "mid", "mid+1", "high"]
SWINGS = ["off", "vertical", "horizontal", "both"]
HA_FANS = ["low", "medium_low", "medium", "medium_high", "high"]
WIG_ID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

Patch = Callable[[Any], None]


def synthetic_wig(unit: str | None = None, dry: bool = False) -> dict[str, Any]:
    """A complete lattice over the Daikin's vocabulary, using the candle's codes.

    With ``dry``, a third mode that runs at one fan and one temperature, the
    shape a real dry mode has (the Komeco's does).
    """
    candle = json.loads(CANDLE.read_text(encoding="utf-8"))
    prontos = [s["pronto"] for s in candle["signals"]]
    coordinates = list(
        itertools.product(("cool", "heat"), FANS, SWINGS, (20, 21, 22))
    )
    if dry:
        coordinates += [("dry", "low", "off", 21), ("dry", "low", "both", 21)]
    cells = []
    for index, (mode, fan, swing, temp) in enumerate(coordinates):
        cells.append({
            "mode": mode, "fan": fan, "swing": swing, "temp": temp,
            "pronto": prontos[index % len(prontos)],
        })
    climate: dict[str, Any] = {
        "min_temp": 20, "max_temp": 22, "precision": 1,
        "modes": ["cool", "heat"] + (["dry"] if dry else []),
        "fan_modes": FANS, "swing_modes": SWINGS,
        "off": prontos[0], "cells": cells,
    }
    if unit is not None:
        climate["unit"] = unit
    return {
        "format": "hair-wig/3", "name": "Synthetic climate", "wig_id": WIG_ID,
        "brand": "Test", "model": "Lattice", "kind": "ac", "signals": [],
        "climate": climate,
    }


def build(
    tmp: Path,
    wig: dict[str, Any],
    *,
    edit_lattice: Callable[[dict[str, Any]], None] | None = None,
    fan_names: list[str] | None = None,
) -> tuple[Path, Path]:
    """Lay out a component directory and a wig file. Return both paths."""
    component = tmp / "custom_components" / "fixture_ir"
    (component / "translations").mkdir(parents=True)
    for name in ("lattice.py", "command.py"):
        shutil.copy(MODULES / name, component / name)
    shipped = {
        "format": "hair-matrix/1",
        "wig": {"wig_id": wig["wig_id"]},
        "climate": copy.deepcopy(wig["climate"]),
    }
    if edit_lattice is not None:
        edit_lattice(shipped)
    (component / "lattice.json").write_text(json.dumps(shipped), encoding="utf-8")
    names = HA_FANS if fan_names is None else fan_names
    translations = {"entity": {"climate": {"fixture": {"state_attributes": {
        "fan_mode": {"state": {k: k.replace("_", " ").title() for k in names}}
    }}}}}
    (component / "translations" / "en.json").write_text(
        json.dumps(translations), encoding="utf-8"
    )
    wig_path = tmp / "synthetic.wig.json"
    wig_path.write_text(json.dumps(wig), encoding="utf-8")
    return component, wig_path


_serial = itertools.count()


def loader(patches: dict[str, Patch] | None = None) -> Callable[[Path, str], Any]:
    """Load each module fresh under a unique name, then apply any patch."""
    patches = patches or {}

    def load(path: Path, stem: str) -> Any:
        name = f"_climate_fixture_{next(_serial)}_{stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if stem in patches:
            patches[stem](module)
        return module

    return load


def run(
    hair: Hair,
    wig: dict[str, Any],
    *,
    patches: dict[str, Patch] | None = None,
    **layout: Any,
) -> Report:
    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        component, wig_path = build(Path(tmp), wig, **layout)
        parsed = hair.wig_format.parse_wig(wig_path.read_text(encoding="utf-8"))
        if not parsed.ok:
            report.fail(f"synthetic wig does not parse: {parsed.errors}")
            return report
        check_climate_integration(
            hair, parsed.wig, wig_path, component, loader(patches), report
        )
    return report


def failed(report: Report, text: str) -> bool:
    return any(text in line for line in report.failures)


# ---------------------------------------------------------------------------
# Scenarios. Each returns a list of problems; empty means it behaved.
# ---------------------------------------------------------------------------


def clean_build_passes(hair: Hair) -> list[str]:
    report = run(hair, synthetic_wig())
    problems = []
    if report.failures:
        problems.append(f"a clean build should pass, failed with {report.failures}")
    facts = report.facts.get("climate_integration") or {}
    if facts.get("cells_reached") != 120:
        problems.append(f"all 120 cells should be reachable, got {facts}")
    if (report.facts.get("recipe") or {}).get("derived") != 1:
        problems.append("the lattice's send count should reach the shared check")
    return problems


def tampered_lattice_refuses(hair: Hair) -> list[str]:
    wig = synthetic_wig()

    def edit(shipped: dict[str, Any]) -> None:
        shipped["climate"]["cells"][7]["pronto"] = wig["climate"]["off"]

    report = run(hair, wig, edit_lattice=edit)
    if failed(report, "is not the wig's climate block"):
        return []
    return [f"a changed cell must refuse, got {report.failures}"]


def wrong_wig_id_refuses(hair: Hair) -> list[str]:
    def edit(shipped: dict[str, Any]) -> None:
        shipped["wig"]["wig_id"] = "00000000-0000-4000-8000-000000000000"

    report = run(hair, synthetic_wig(), edit_lattice=edit)
    if failed(report, "names wig"):
        return []
    return [f"a lattice naming another wig must refuse, got {report.failures}"]


def drifting_resolver_refuses(hair: Hair) -> list[str]:
    def drift(module: Any) -> None:
        original = module.resolve_cell

        def off_by_one(lattice, mode, fan=None, swing=None, temp=None, *,
                       branches=None):
            nudged = None if temp is None else temp + 1
            return original(lattice, mode, fan, swing, nudged, branches=branches)

        module.resolve_cell = off_by_one

    report = run(hair, synthetic_wig(), patches={"lattice": drift})
    if failed(report, "resolver and HAIR's disagree"):
        return []
    return [f"a resolver one degree out must refuse, got {report.failures}"]


def swapped_fans_refuse(hair: Hair) -> list[str]:
    def swap(module: Any) -> None:
        module.FAN_MODES = {
            "low": "low", "medium_low": "mid", "medium": "low+1",
            "medium_high": "mid+1", "high": "high",
        }

    report = run(hair, synthetic_wig(), patches={"lattice": swap})
    if failed(report, "fan words run"):
        return []
    return [f"two swapped fan speeds must refuse, got {report.failures}"]


def untranslated_fan_refuses(hair: Hair) -> list[str]:
    report = run(hair, synthetic_wig(), fan_names=HA_FANS[:-1])
    if failed(report, "no English name"):
        return []
    return [f"a fan word with no English name must refuse, got {report.failures}"]


def missing_terminator_refuses(hair: Hair) -> list[str]:
    def unterminated(module: Any) -> None:
        module.terminate = lambda timings: list(timings)

    report = run(hair, synthetic_wig(), patches={"command": unterminated})
    if failed(report, "terminator"):
        return []
    return [f"codes without the terminator must refuse, got {report.failures}"]


def fahrenheit_refuses(hair: Hair) -> list[str]:
    report = run(hair, synthetic_wig(unit="F"))
    if failed(report, "cannot load its own lattice"):
        return []
    return [f"a Fahrenheit lattice must refuse, got {report.failures}"]


def _with_dry(module: Any) -> None:
    module.HVAC_MODES = {"cool": "cool", "heat": "heat", "dry": "dry"}


def _reference_offers(module: Any) -> None:
    """What an integration's Resolver.offers looks like: read off the lattice."""
    _with_dry(module)

    def offers(self: Any, hvac_mode: str) -> dict[str, list[Any]]:
        mode = module.HVAC_MODES.get(hvac_mode)
        cells = [c for c in self.lattice.cells if c.mode == mode]
        fans = [f for f in self.lattice.fan_modes if any(c.fan == f for c in cells)]
        swings = [
            s for s in self.lattice.swing_modes if any(c.swing == s for c in cells)
        ]
        return {
            "fan_modes": [module.ha_fan_mode(f) for f in fans],
            "swing_modes": swings,
            "temperatures": sorted({c.temp for c in cells if c.temp is not None}),
        }

    module.Resolver.offers = offers


def modes_that_differ_need_offers(hair: Hair) -> list[str]:
    report = run(hair, synthetic_wig(dry=True), patches={"lattice": _with_dry})
    if failed(report, "does not say what each mode offers"):
        return []
    return [f"a dry mode with one fan needs offers(), got {report.failures}"]


def matching_offers_pass(hair: Hair) -> list[str]:
    report = run(hair, synthetic_wig(dry=True), patches={"lattice": _reference_offers})
    problems = []
    if report.failures:
        problems.append(f"offers matching the wig should pass, got {report.failures}")
    facts = report.facts.get("climate_integration") or {}
    if facts.get("cells_reached") != 122:
        problems.append(f"all 122 cells should be reachable, got {facts}")
    return problems


def wrong_offers_refuse(hair: Hair) -> list[str]:
    def overclaim(module: Any) -> None:
        _reference_offers(module)
        honest = module.Resolver.offers

        def offers(self: Any, hvac_mode: str) -> dict[str, list[Any]]:
            out = honest(self, hvac_mode)
            if hvac_mode == "dry":
                out["fan_modes"] = ["low", "high"]
            return out

        module.Resolver.offers = offers

    report = run(hair, synthetic_wig(dry=True), patches={"lattice": overclaim})
    if failed(report, "Resolver.offers disagrees"):
        return []
    return [f"offering a fan the dry mode lacks must refuse, got {report.failures}"]


SCENARIOS: list[tuple[str, Callable[[Hair], list[str]]]] = [
    ("a clean climate build passes every check", clean_build_passes),
    ("a lattice that is not the wig's refuses", tampered_lattice_refuses),
    ("a lattice naming another wig refuses", wrong_wig_id_refuses),
    ("a resolver that drifts from HAIR's refuses", drifting_resolver_refuses),
    ("fan words in the wrong order refuse", swapped_fans_refuse),
    ("a fan word with no English name refuses", untranslated_fan_refuses),
    ("a code sent without the terminator refuses", missing_terminator_refuses),
    ("a Fahrenheit lattice refuses", fahrenheit_refuses),
    ("modes that differ need Resolver.offers", modes_that_differ_need_offers),
    ("offers that match the wig pass, mode by mode", matching_offers_pass),
    ("offering a setting a mode lacks refuses", wrong_offers_refuse),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    args = parser.parse_args(argv)
    hair = Hair(args.hair.resolve())

    print(f"climate checks against HAIR {hair.version}\n")
    failures = 0
    for title, scenario in SCENARIOS:
        problems = scenario(hair)
        if problems:
            failures += 1
            print(f"  FAIL  {title}")
            for line in problems:
                print(f"          {line}")
        else:
            print(f"  PASS  {title}")
    print()
    if failures:
        print(f"{failures} scenario(s) misbehaved.")
        return 1
    print("ALL SCENARIOS BEHAVE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
