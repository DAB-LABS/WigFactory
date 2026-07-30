#!/usr/bin/env python3
"""What in the Wig Shop is ready to become an integration?

The factory runs over many wigs, and deciding which ones to build by opening
files is not a plan. Every criterion that matters is something the gate
already computes, so this walks the shop clone, runs the input gate on each
wig, and sorts the results.

    verify/survey_shop.py
    verify/survey_shop.py --json

The output is a proposal, not an instruction. Read it, pick the wigs worth
building, and build those. Nothing here generates anything and nothing here
writes to the shop.

Sorting:

  READY        passes the input gate and no integration exists yet
  BUILT        an integration already exists for this stem
  FITTINGS     otherwise fine, below the promotion bar
  DEFECTS      the wig's own contents contradict themselves
  UNUSABLE     will not parse, or carries no complete fitting at all

DEFECTS is the interesting bucket, and on converted files it is the biggest.
A wig lands there when the gate found something wrong with the codes rather
than with the paperwork: a lattice hole, a truncated frame, two temperatures
sharing one payload. Those need fixing at the source, not here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_wig import (  # noqa: E402
    DEFAULT_HAIR,
    DEFAULT_SHOP,
    PROMOTION_HANDLES,
    REPO_ROOT,
    Hair,
    Report,
    decode_wig,
    read_exemptions,
    run_input_gate,
    shop_provenance,
    wig_slug,
)

# A failure mentioning any of these is about the paperwork rather than the
# codes. Everything else that fails is a defect in the wig itself.
_HANDLE_MARKERS = ("distinct GitHub accounts", "promotion bar")
_UNUSABLE_MARKERS = (
    "does not parse",
    "carries no fitting",
    "no complete fitting survived",
    "cannot read",
    "has neither signals nor",
)


def existing_builds(root: Path) -> set[str]:
    """Stems the factory has already produced an integration for."""
    found: set[str] = set()
    for codes in root.glob("*/*/custom_components/*/codes.py"):
        found.add(codes.parents[2].parent.name)
    for climate in root.glob("*/*/custom_components/*/cells.py"):
        found.add(climate.parents[2].parent.name)
    return found


def classify(report: Report, slug: str, built: set[str]) -> tuple[str, list[str]]:
    """Which bucket a wig belongs in, and why."""
    failures = report.failures
    if any(m in f for f in failures for m in _UNUSABLE_MARKERS):
        return "UNUSABLE", failures
    defects = [
        f
        for f in failures
        if not any(m in f for m in _HANDLE_MARKERS)
    ]
    if defects:
        return "DEFECTS", defects
    handles = [f for f in failures if any(m in f for m in _HANDLE_MARKERS)]
    if handles:
        return "FITTINGS", handles
    if slug in built:
        return "BUILT", []
    return "READY", []


def survey(
    hair: Hair, shop: Path, root: Path, exemptions: Path | None
) -> list[dict[str, Any]]:
    """Run the input gate over every wig in the shop clone."""
    waivers = read_exemptions(exemptions) if exemptions else {}
    built = existing_builds(root)
    rows: list[dict[str, Any]] = []
    for path in sorted(shop.glob("wigs/*/*.wig.json")):
        slug = wig_slug(path)
        report = Report()
        waiver = waivers.get(slug.casefold())
        try:
            wig = run_input_gate(hair, path, report, PROMOTION_HANDLES, waiver)
            if wig is not None:
                decode_wig(hair, wig, report)
        except BaseException as err:  # noqa: BLE001 - a survey never dies
            report.fail(f"the gate raised {err!r} on this wig")
            wig = None
        bucket, why = classify(report, slug, built)
        rows.append(
            {
                "slug": slug,
                "brand": report.facts.get("brand"),
                "model": report.facts.get("model"),
                "kind": report.facts.get("kind"),
                "shape": report.facts.get("shape"),
                "rows": report.facts.get(
                    "cell_count", report.facts.get("signal_count")
                ),
                "protocol": report.facts.get("protocol"),
                "accounts": report.facts.get("promotion_handles", 0),
                "waived": waiver is not None and bucket != "FITTINGS",
                "bucket": bucket,
                "why": why,
            }
        )
    return rows


ORDER = ("READY", "FITTINGS", "DEFECTS", "UNUSABLE", "BUILT")


def print_survey(rows: list[dict[str, Any]], provenance: dict[str, str] | None) -> None:
    if provenance:
        print(f"Wig Shop at {provenance['short']} ({provenance['date']})")
    print(f"{len(rows)} wig(s) in the shop\n")
    for bucket in ORDER:
        here = [r for r in rows if r["bucket"] == bucket]
        if not here:
            continue
        print(f"{bucket}  ({len(here)})")
        for r in here:
            shape = r["shape"] or "?"
            size = f"{r['rows']} {'cells' if shape == 'matrix' else 'signals'}"
            waived = "  [waived]" if r["waived"] else ""
            print(
                f"   {r['slug']:34} {str(r['brand'] or '?'):12} "
                f"{size:12} {str(r.get('protocol') or ''):10} "
                f"{r['accounts']}/{PROMOTION_HANDLES}{waived}"
            )
            for line in r["why"][:3]:
                print(f"        {line[:150]}")
        print()

    ready = [r for r in rows if r["bucket"] == "READY"]
    if ready:
        print("Build candidates, in the owner's gift:")
        for r in ready:
            print(f"   {r['slug']}")
    else:
        print("Nothing is ready to build.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    parser.add_argument("--shop", type=Path, default=DEFAULT_SHOP)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--exemption",
        type=Path,
        default=REPO_ROOT / "EXEMPTIONS.md",
        help="waiver file, so a waived wig sorts as ready rather than short",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    shop = args.shop.resolve()
    if not shop.is_dir():
        print(f"no Wig Shop clone at {shop}. Run ./setup.sh first.")
        return 1

    hair = Hair(args.hair.resolve())
    rows = survey(
        hair,
        shop,
        args.root.resolve(),
        args.exemption if args.exemption.is_file() else None,
    )
    provenance = shop_provenance(shop)
    if args.json:
        print(json.dumps({"shop": provenance, "wigs": rows}, indent=2))
    else:
        print_survey(rows, provenance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
