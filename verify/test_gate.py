#!/usr/bin/env python3
"""Behaviour tests for the gate's reading of HAIR 0.12 to 0.16.

test_recipe.py pins the digest contract. This pins what the gate SAYS about a
wig, against real shelf wigs vendored in verify/fixtures/ and small mutations
of them, so each of these is checked on a wig nobody hand-built:

- the comb is run live, and a stored receipt is read as history, not answer
- decode trust: a label that does not account for its capture refuses
- carrierless codes refuse
- hair-wig/4 extra lattices refuse until the gate checks them
- repair records and attestations are read, reported, and signed by nothing

    .venv/bin/python verify/test_gate.py
    .venv/bin/python verify/test_gate.py --hair /path/to/HAIR

Exit 0 means every scenario behaved as expected. No pytest: the verification
environment is requirements.txt and nothing else, on purpose.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_wig import (  # noqa: E402
    DEFAULT_HAIR,
    Hair,
    Report,
    decode_wig,
    run_input_gate,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CANDLE = "sanmli-candles-th05.wig.json"
DREO = "dreo-fan-dr-haf004s-perfect-fit.wig.json"
WINIX = "winix-fan-5500-perfect-fit.wig.json"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def gate(hair: Hair, data: dict[str, Any]) -> Report:
    """Run the input gate and the decode over a wig given as a dict."""
    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wig.wig.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        wig = run_input_gate(hair, path, report)
        if wig is not None:
            decode_wig(hair, wig, report)
    return report


def said(report: Report, text: str) -> bool:
    return any(text in line for line in report.checks + report.notes + report.failures)


def failed(report: Report, text: str) -> bool:
    return any(text in line for line in report.failures)


# ---------------------------------------------------------------------------
# Scenarios. Each returns a list of problems; empty means it behaved.
# ---------------------------------------------------------------------------


def candle_is_clean(hair: Hair) -> list[str]:
    report = gate(hair, load(CANDLE))
    problems = []
    if not report.passed:
        problems.append(f"the candle should pass, failed with {report.failures}")
    live = (report.facts.get("comb") or {}).get("live") or {}
    if live.get("suspects") != 0:
        problems.append(f"the candle should comb clean live, got {live}")
    if report.facts.get("decode_trust", {}).get("uncovered"):
        problems.append("every candle label accounts for its capture")
    return problems


def dreo_receipt_is_history(hair: Hair) -> list[str]:
    report = gate(hair, load(DREO))
    problems = []
    comb = report.facts.get("comb") or {}
    if (comb.get("receipt") or {}).get("suspects") != 0:
        problems.append("the Dreo's stored receipt records 0 suspects")
    if (comb.get("live") or {}).get("suspects", 0) < 1:
        problems.append(f"a live comb should flag the Dreo, got {comb}")
    if not said(report, "the live comb finds"):
        problems.append("the gate should say the receipt and the live comb differ")
    return problems


def winix_trust_unverified(hair: Hair) -> list[str]:
    report = gate(hair, load(WINIX))
    problems = []
    if not report.passed:
        problems.append(f"the Winix should pass, failed with {report.failures}")
    trust = report.facts.get("decode_trust") or {}
    if len(trust.get("unverified", [])) != 5:
        problems.append(f"all five Winix labels are unverifiable, got {trust}")
    if trust.get("uncovered"):
        problems.append("unverifiable is not uncovered, and must not refuse")
    return problems


def uncovered_label_refuses(hair: Hair) -> list[str]:
    original = hair.covers_capture
    hair.covers_capture = lambda raw: False  # type: ignore[method-assign]
    try:
        report = gate(hair, load(CANDLE))
    finally:
        hair.covers_capture = original  # type: ignore[method-assign]
    if failed(report, "does not account for the whole capture"):
        return []
    return ["a label HAIR says does not cover its capture must refuse"]


def carrierless_refuses(hair: Hair) -> list[str]:
    data = load(CANDLE)
    words = data["signals"][0]["pronto"].split()
    words[0] = "0100"
    data["signals"][0]["pronto"] = " ".join(words)
    report = gate(hair, data)
    if failed(report, "carry no carrier"):
        return []
    return [f"a 0100 code must refuse, got {report.failures}"]


def extras_refuse(hair: Hair) -> list[str]:
    candle = load(CANDLE)
    pronto = [s["pronto"] for s in candle["signals"][:4]]
    cells = [
        {"mode": "cool", "fan": "auto", "temp": 20 + i, "pronto": p}
        for i, p in enumerate(pronto)
    ]
    data = {
        "format": "hair-wig/4",
        "name": "Synthetic v4",
        "kind": "ac",
        "signals": [],
        "climate": {
            "min_temp": 20,
            "max_temp": 23,
            "modes": ["cool"],
            "fan_modes": ["auto"],
            "off": pronto[0],
            "cells": cells,
            "extras": [
                {"axis": "preset", "key": "eco", "cells": copy.deepcopy(cells[:2])}
            ],
        },
    }
    report = gate(hair, data)
    if not failed(report, "extra lattice(s) (hair-wig/4)"):
        return [f"an extras lattice must refuse, got {report.failures}"]
    return []


def repairs_are_read_and_unsigned(hair: Hair) -> list[str]:
    data = load(CANDLE)
    data["signals"][0]["hair_repair"] = {"source": "capture", "tier": "air-tested"}
    data["signals"][1]["hair_repair"] = {
        "source": "synthesized",
        "tier": "rule-derived",
    }
    data["signals"][2]["hair_repair"] = {"source": "paste"}
    report = gate(hair, data)
    problems = []
    if not report.passed:
        problems.append(
            "repair records sit outside every hash, so the candle's signed "
            f"fittings should still verify; failed with {report.failures}"
        )
    repairs = report.facts.get("repairs") or {}
    if repairs.get("tiers") != {"air-tested": 1, "rule-derived": 1, "unstated": 1}:
        problems.append(f"tier count wrong: {repairs}")
    if not said(report, "nothing signs"):
        problems.append("the gate must say repair records are unsigned")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "publish"))
    from _common import provenance_lines

    lines = provenance_lines(report.facts)
    if not any(line.startswith("Repaired codes 3") for line in lines):
        problems.append("the published provenance must carry the repair count")
    return problems


def repair_that_did_not_take(hair: Hair) -> list[str]:
    data = load(DREO)
    for signal in data["signals"]:
        if signal["alias"] == "Oscillate Horizontal":
            signal["hair_repair"] = {"source": "capture", "tier": "air-tested"}
    report = gate(hair, data)
    if said(report, "still flagged by the live comb: Oscillate Horizontal"):
        return []
    return ["a repaired code the comb still flags must be called out"]


def attestations_expire(hair: Hair) -> list[str]:
    data = load(DREO)
    target = next(s for s in data["signals"] if s["alias"] == "Speed Down")
    digest = hair.row_digest(target["pronto"], target.get("ditto_count", 0), False)
    data["comb"]["attested"] = [
        {"key": "x", "target": "Speed Down", "kind": "command", "digest": digest},
        {"key": "y", "target": "Oscillate Vertical", "kind": "command",
         "digest": "0000000000000000"},
    ]
    report = gate(hair, data)
    attested = (report.facts.get("comb") or {}).get("attested") or {}
    problems = []
    if attested.get("standing") != ["Speed Down"]:
        problems.append(f"the matching answer should stand, got {attested}")
    if attested.get("expired") != ["Oscillate Vertical"]:
        problems.append(f"the stale answer should have expired, got {attested}")
    return problems


SCENARIOS: list[tuple[str, Callable[[Hair], list[str]]]] = [
    ("the candle combs clean and every label covers its capture", candle_is_clean),
    ("the Dreo's receipt is read as history, the live comb as the answer",
     dreo_receipt_is_history),
    ("the Winix's labels are unverifiable, which notes and does not refuse",
     winix_trust_unverified),
    ("a label that does not cover its capture refuses", uncovered_label_refuses),
    ("a carrierless code refuses", carrierless_refuses),
    ("a hair-wig/4 extras lattice refuses until it is checked", extras_refuse),
    ("repair records are read, counted, published, and signed by nothing",
     repairs_are_read_and_unsigned),
    ("a repair the comb still flags is called out", repair_that_did_not_take),
    ("attestations stand while their bytes match and expire when not",
     attestations_expire),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    args = parser.parse_args(argv)
    hair = Hair(args.hair.resolve())

    print(f"gate behaviour against HAIR {hair.version}\n")
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
