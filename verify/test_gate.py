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
- on a matrix, a wrong-state finding nobody has answered refuses

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
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
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


WRONG_STATE_REFUSAL = "send a state other than the one on their label"


class _Planted:
    """A live comb report with extra findings planted in it.

    No wig on the shelf has a wrong-state cell, which is the point of the
    shelf, so the finding is planted on top of HAIR's real report for a
    small synthetic matrix. Everything else the gate reads stays real.
    """

    def __init__(self, real: Any, extra: list[Any]) -> None:
        self.findings = list(real.findings) + extra
        self.coverage = real.coverage

    @property
    def suspects(self) -> int:
        return sum(1 for f in self.findings if not f.advisory)

    def counts(self) -> dict[str, int]:
        return dict(Counter(f.check for f in self.findings if not f.advisory))


def _planted_gate(
    hair: Hair, data: dict[str, Any], key: str, check: str = "field-mismatch"
) -> Report:
    finding = SimpleNamespace(check=check, keys=[key], advisory=False)
    original = hair.comb
    hair.comb = lambda wig: _Planted(original(wig), [finding])  # type: ignore[method-assign]
    try:
        return gate(hair, data)
    finally:
        hair.comb = original  # type: ignore[method-assign]


def _small_matrix() -> dict[str, Any]:
    pronto = [s["pronto"] for s in load(CANDLE)["signals"][:4]]
    return {
        "format": "hair-wig/3",
        "name": "Synthetic matrix",
        "kind": "ac",
        "signals": [],
        "climate": {
            "min_temp": 20,
            "max_temp": 23,
            "modes": ["cool"],
            "fan_modes": ["auto"],
            "off": pronto[0],
            "cells": [
                {"mode": "cool", "fan": "auto", "temp": 20 + i, "pronto": p}
                for i, p in enumerate(pronto)
            ],
        },
    }


def _first_cell(hair: Hair, data: dict[str, Any]) -> tuple[str, str]:
    """HAIR's key for the first cell, and the digest an answer would carry."""
    wig = hair.wig_format.parse_wig(json.dumps(data)).wig
    cell = wig.climate.cells[0]
    return hair.cell_key(cell), hair.row_digest(cell.pronto, 0, False)


def wrong_state_refuses_on_a_matrix(hair: Hair) -> list[str]:
    data = _small_matrix()
    key, _ = _first_cell(hair, data)
    report = _planted_gate(hair, data, key)
    problems = []
    if not failed(report, WRONG_STATE_REFUSAL):
        problems.append(f"an unanswered field-mismatch on {key} must refuse")
    wrong = (report.facts.get("comb") or {}).get("wrong_state") or {}
    if key not in wrong.get("unanswered", []):
        problems.append(f"{key} should be listed as unanswered, got {wrong}")
    return problems


def answered_wrong_state_stands(hair: Hair) -> list[str]:
    data = _small_matrix()
    key, digest = _first_cell(hair, data)
    data["comb"] = {
        "suspects": 0,
        "counts": {},
        "attested": [{"key": "z", "target": key, "kind": "cell", "digest": digest}],
    }
    report = _planted_gate(hair, data, key)
    wrong = (report.facts.get("comb") or {}).get("wrong_state") or {}
    problems = []
    if key not in wrong.get("answered", []) or key in wrong.get("unanswered", []):
        problems.append(f"a standing answer on {key} should settle it, got {wrong}")
    if any(key in line and WRONG_STATE_REFUSAL in line for line in report.failures):
        problems.append(f"an answered cell must not be named in a refusal: {key}")
    return problems


def wrong_state_on_commands_only_notes(hair: Hair) -> list[str]:
    report = _planted_gate(hair, load(CANDLE), "Power")
    if failed(report, WRONG_STATE_REFUSAL):
        return ["a command wig reports wrong-state findings and never refuses on them"]
    if not said(report, "send a state other than the one they are labelled with"):
        return ["a command wig should still note its wrong-state findings"]
    return []


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
    ("an unanswered wrong-state cell refuses a matrix",
     wrong_state_refuses_on_a_matrix),
    ("a standing answer settles a wrong-state cell",
     answered_wrong_state_stands),
    ("a wrong-state finding on a command wig notes and does not refuse",
     wrong_state_on_commands_only_notes),
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
