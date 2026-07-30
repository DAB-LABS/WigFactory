#!/usr/bin/env python3
"""Work out how a state matrix packs its fields, mechanically.

A stateful device sends its whole configuration in one frame: mode, fan
speed, swing, temperature, usually a checksum, and a large constant part that
never moves. Reading that structure out of a wig by eye is not realistic. The
Gree file has 960 cells of 66 bits each, and the answer is 15 bits spread
across five runs.

But it is entirely mechanical. Every cell of one device sends the same frame
shape, so line them up, find the bit positions that move, group them into
contiguous runs, and ask which dimension each run tracks. That is what this
does. It reads a wig and prints a field map.

The judgement stays with a person: deciding that a four-bit run really is the
temperature rather than something correlated with it, recognising a checksum,
and choosing what the integration exposes. The tool exists so that judgement
is applied to a field map instead of to 63KB of hex.

    verify/derive_fields.py --wig WIG [--hair PATH]

Nothing here is a check and nothing here refuses. `verify_wig.py` is the
gate; this is a microscope.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_wig import DEFAULT_HAIR, Hair  # noqa: E402

# A space longer than this ends a frame. Every AC protocol seen so far puts
# 8ms or more between frames and never more than about 2ms inside one.
FRAME_GAP_US = 5000

# Pulse distance coding: the mark is constant and the space carries the bit.
# Anything above this is a one. Comfortably clear of both populations on
# every device measured, where zero spaces sit near 500us and one spaces near
# 1600us.
ONE_SPACE_US = 1000

DIMENSIONS = ("mode", "fan", "swing", "temp")


def frames(hair: Hair, pronto: str) -> list[list[int]] | None:
    """Split a Pronto string into frames on any gap over ``FRAME_GAP_US``."""
    timings = hair.timings_from_pronto(pronto)
    if timings is None:
        return None
    out: list[list[int]] = []
    current: list[int] = []
    for value in timings:
        if value < 0 and -value > FRAME_GAP_US:
            if current:
                out.append(current)
                current = []
            continue
        current.append(value)
    if current:
        out.append(current)
    return out


def bits(hair: Hair, pronto: str) -> list[int] | None:
    """Every payload bit in a cell, frames concatenated, leaders dropped.

    Returns None when the frame does not look like pulse distance coding, so
    a device this tool cannot read says so rather than inventing a field map.
    """
    split = frames(hair, pronto)
    if not split:
        return None
    out: list[int] = []
    for frame in split:
        body = frame[2:]  # the leader mark and space carry no data
        if len(body) < 2:
            continue
        for i in range(0, len(body) - 1, 2):
            mark, space = body[i], body[i + 1]
            if mark <= 0 or space >= 0:
                return None
            out.append(1 if -space > ONE_SPACE_US else 0)
    return out or None


def runs_of(positions: list[int]) -> list[list[int]]:
    """Group sorted bit positions into contiguous runs."""
    if not positions:
        return []
    out: list[list[int]] = []
    current = [positions[0]]
    for p in positions[1:]:
        if p == current[-1] + 1:
            current.append(p)
        else:
            out.append(current)
            current = [p]
    out.append(current)
    return out


def value_of(bit_list: list[int], run: list[int]) -> int:
    """Read a run as an integer, least significant bit first."""
    return sum(bit_list[p] << k for k, p in enumerate(run))


def analyse(hair: Hair, wig: Any) -> dict[str, Any]:
    """The field map for one matrix wig."""
    matrix = wig.climate
    rows: list[tuple[dict[str, Any], list[int]]] = []
    unreadable: list[str] = []
    for cell in matrix.cells:
        b = bits(hair, cell.pronto)
        if b is None:
            unreadable.append(hair.cell_key(cell))
            continue
        rows.append(
            (
                {
                    "mode": cell.mode,
                    "fan": cell.fan,
                    "swing": cell.swing,
                    "temp": cell.temp,
                },
                b,
            )
        )

    widths = collections.Counter(len(b) for _, b in rows)
    result: dict[str, Any] = {
        "cells_read": len(rows),
        "cells_unreadable": unreadable,
        "bit_widths": dict(widths),
    }
    if not rows:
        return result

    width, _ = widths.most_common(1)[0]
    rows = [(c, b) for c, b in rows if len(b) == width]
    result["bit_width"] = width

    varying = [
        i for i in range(width) if len({b[i] for _, b in rows}) > 1
    ]
    result["constant_bits"] = width - len(varying)

    fields = []
    for run in runs_of(varying):
        by_dim: dict[str, dict[Any, set[int]]] = {
            d: collections.defaultdict(set) for d in DIMENSIONS
        }
        for coords, b in rows:
            v = value_of(b, run)
            for d in DIMENSIONS:
                by_dim[d][coords[d]].add(v)
        # A run is "explained by" a dimension when fixing that dimension
        # fixes the run's value. More than one can qualify on a small
        # lattice, which is itself worth seeing.
        explained = [
            d
            for d in DIMENSIONS
            if len(by_dim[d]) > 1
            and all(len(v) == 1 for v in by_dim[d].values())
        ]
        entry: dict[str, Any] = {
            "bits": [run[0], run[-1]],
            "width": len(run),
            "distinct_values": len({value_of(b, run) for _, b in rows}),
            "explained_by": explained,
        }
        for d in explained:
            entry[f"{d}_map"] = {
                str(k): sorted(v)[0] for k, v in sorted(
                    by_dim[d].items(), key=lambda i: str(i[0])
                )
            }
        fields.append(entry)
    result["fields"] = fields
    return result


def print_report(wig: Any, result: dict[str, Any]) -> None:
    print(f"wig:    {wig.brand} {wig.model}")
    print(f"cells:  {result['cells_read']} read", end="")
    if result["cells_unreadable"]:
        print(f", {len(result['cells_unreadable'])} not pulse distance", end="")
    print()
    if "bit_width" not in result:
        print("\nNo cell decoded as pulse distance coding. This device uses a "
              "frame shape this tool does not read, and the field map has to "
              "be worked out by hand.")
        return
    if len(result["bit_widths"]) > 1:
        print(f"        bit widths present: {result['bit_widths']} "
              f"(analysing the {result['bit_width']} bit majority)")
    print(f"frame:  {result['bit_width']} bits, "
          f"{result['constant_bits']} of them constant across every cell")
    print()
    for f in result["fields"]:
        lo, hi = f["bits"]
        span = f"bits {lo}" if lo == hi else f"bits {lo}..{hi}"
        who = ", ".join(f["explained_by"]) or "no single dimension"
        print(f"  {span:16} {f['width']:2} wide, "
              f"{f['distinct_values']:3} distinct  ->  {who}")
        for d in f["explained_by"]:
            mapping = f[f"{d}_map"]
            pairs = ", ".join(f"{k}={v}" for k, v in mapping.items())
            print(f"       {d}: {pairs}")
    unexplained = [f for f in result["fields"] if not f["explained_by"]]
    if unexplained:
        print()
        print("Runs no single dimension explains are usually a checksum, or a "
              "field that depends on more than one coordinate. Neither is a "
              "problem; both mean the encoder needs that run computed rather "
              "than looked up.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive a matrix wig's field map.")
    parser.add_argument("--wig", required=True, help="path to a .wig.json")
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    args = parser.parse_args(argv)

    hair = Hair(args.hair.resolve())
    result = hair.wig_format.parse_wig(Path(args.wig).read_text(encoding="utf-8"))
    if not result.ok:
        print("wig does not parse:", "; ".join(result.errors))
        return 1
    wig = result.wig
    if getattr(wig, "climate", None) is None:
        print("not a matrix wig; there is no lattice to line up")
        return 1

    analysis = analyse(hair, wig)
    if args.json:
        print(json.dumps(analysis, indent=2, default=str))
    else:
        print_report(wig, analysis)
    return 0


if __name__ == "__main__":
    sys.exit(main())
