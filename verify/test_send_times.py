#!/usr/bin/env python3
"""Parity and behaviour vectors for the send-times reader.

Two readers exist for one field, and that is a deliberate risk. HAIR owns the
rule; the factory keeps a fallback for HAIR checkouts older than 0.9.0, which
is where ``fitting_send_times_max`` first appeared. A fallback that drifts from
the thing it falls back to is worse than no fallback at all, because it fails
quietly and in the direction nobody checks.

So this compares the two directly, vector by vector, exactly the way
``github_key`` is held in step with the Wig Shop's copy. Run it after touching
either reader:

    .venv/bin/python verify/test_send_times.py
    .venv/bin/python verify/test_send_times.py --hair /path/to/HAIR

With a HAIR checkout older than 0.9.0 the parity half is skipped with a note
and the behaviour half still runs. Exit 0 means agreement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_wig import (  # noqa: E402
    SEND_TIMES_KEY,
    SEND_TIMES_MAX,
    SEND_TIMES_MIN,
    Hair,
    read_default_send_count,
    read_send_times,
)

# Every shape a hand-edited or machine-written fitting has been seen to carry,
# plus the ones that would be embarrassing to get wrong. ``None`` means the key
# is absent entirely, which is a different statement from any value.
VECTORS: list[Any] = [
    None,
    0,
    -1,
    -1000,
    1,
    2,
    3,
    9,
    10,
    11,
    1000,
    True,
    False,
    "3",
    "",
    3.0,
    [3],
    {},
    {"x": 1},
]

# What the factory reader must return, independent of HAIR. Written out rather
# than derived, so a change to the clamp has to be made twice on purpose.
EXPECTED: dict[str, int | None] = {
    "<absent>": None,
    "0": 1,
    "-1": 1,
    "-1000": 1,
    "1": 1,
    "2": 2,
    "3": 3,
    "9": 9,
    "10": 10,
    "11": 10,
    "1000": 10,
    "True": None,
    "False": None,
    "'3'": None,
    "''": None,
    "3.0": None,
    "[3]": None,
    "{}": None,
    "{'x': 1}": None,
}


def entry_for(value: Any) -> dict[str, Any]:
    """A fitting-shaped dict carrying ``value``, or nothing at all."""
    if value is None:
        return {"handle": "somebody"}
    return {"handle": "somebody", SEND_TIMES_KEY: value}


def label(value: Any) -> str:
    return "<absent>" if value is None else repr(value)


def check_behaviour() -> list[str]:
    """The factory reader on its own terms."""
    problems: list[str] = []
    for value in VECTORS:
        key = label(value)
        got = read_send_times(entry_for(value))
        want = EXPECTED[key]
        if got != want:
            problems.append(f"{key}: factory read {got!r}, expected {want!r}")

    # The two statements the whole field turns on, asserted separately because
    # collapsing them is the mistake this file exists to catch.
    if read_send_times({"handle": "x"}) is not None:
        problems.append("absent must read as None, never as 1")
    if read_send_times({SEND_TIMES_KEY: 1}) != 1:
        problems.append("an explicit 1 must read as 1, it is a measurement")
    if read_send_times({SEND_TIMES_KEY: True}) is not None:
        problems.append("True must be refused, not read as 1")
    if SEND_TIMES_MIN != 1:
        problems.append(f"the floor moved to {SEND_TIMES_MIN}")
    return problems


def check_parity(hair_root: Path) -> tuple[list[str], str, bool]:
    """The factory reader against HAIR's, vector by vector.

    Returns the problems, a line to print, and whether it actually ran.
    """
    hair = Hair(hair_root)
    theirs = getattr(hair.wig_fitting, "_read_send_times", None)
    if theirs is None:
        return (
            [],
            (
                f"HAIR {hair.version} at {hair_root} has no _read_send_times, "
                f"so there is nothing to compare against. This is the case the "
                f"factory fallback exists for."
            ),
            False,
        )

    problems: list[str] = []
    for value in VECTORS:
        entry = entry_for(value)
        mine, hairs = read_send_times(entry), theirs(entry)
        if mine != hairs:
            problems.append(
                f"{label(value)}: factory read {mine!r}, HAIR read {hairs!r}"
            )

    their_max = getattr(hair.wig_fitting, "MAX_SEND_COUNT", None)
    if their_max is None:
        from importlib import import_module

        their_max = getattr(
            import_module("custom_components.hair.const"), "MAX_SEND_COUNT", None
        )
    if their_max is not None and int(their_max) != SEND_TIMES_MAX:
        problems.append(
            f"ceiling drift: HAIR clamps to {their_max}, the factory clamps to "
            f"{SEND_TIMES_MAX}"
        )
    return (
        problems,
        f"compared {len(VECTORS)} vectors against HAIR {hair.version}",
        True,
    )


def check_const_parsing() -> list[str]:
    """``const.py`` is parsed, not imported, so parsing has to be right."""
    import tempfile

    problems: list[str] = []
    cases = [
        ("DEFAULT_SEND_COUNT = 3\n", {"DEFAULT_SEND_COUNT": 3}),
        (
            "DEFAULT_SEND_COUNT = 3\nMIN_SEND_COUNT = 1\nMAX_SEND_COUNT = 10\n",
            {
                "DEFAULT_SEND_COUNT": 3,
                "MIN_SEND_COUNT": 1,
                "MAX_SEND_COUNT": 10,
            },
        ),
        # A bool is an int and would otherwise parse as 1.
        ("DEFAULT_SEND_COUNT = True\n", {}),
        # Not a literal, so not something to guess at.
        ("DEFAULT_SEND_COUNT = 1 + 2\n", {}),
        # Nested inside anything is not a module level default.
        ("class C:\n    DEFAULT_SEND_COUNT = 3\n", {}),
        ("", {}),
        ("this is not python(\n", {}),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for source, want in cases:
            (directory / "const.py").write_text(source, encoding="utf-8")
            got = read_default_send_count(directory)
            if got != want:
                problems.append(
                    f"const.py parse of {source!r}: got {got!r}, wanted {want!r}"
                )
    # A directory with no const.py at all must read as nothing, not raise.
    with tempfile.TemporaryDirectory() as tmp:
        if read_default_send_count(Path(tmp)) != {}:
            problems.append("a missing const.py must read as no constants")
    return problems


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hair",
        type=Path,
        default=repo_root / "reference" / "HAIR",
        help="path to a HAIR checkout to compare against",
    )
    args = parser.parse_args(argv)

    problems = check_behaviour()
    for line in problems:
        print(f"  FAIL  behaviour: {line}")
    if not problems:
        print(f"  PASS  behaviour: {len(VECTORS)} vectors read as specified")

    const_problems = check_const_parsing()
    for line in const_problems:
        print(f"  FAIL  const.py: {line}")
    if not const_problems:
        print("  PASS  const.py: parsed, and a bool is not a send count")

    parity_problems: list[str] = []
    if args.hair.exists():
        parity_problems, message, ran = check_parity(args.hair.resolve())
        for line in parity_problems:
            print(f"  FAIL  parity: {line}")
        if parity_problems:
            pass
        elif ran:
            print(f"  PASS  parity: {message}")
        else:
            print(f"  NOTE  parity skipped: {message}")
    else:
        print(f"  NOTE  no HAIR checkout at {args.hair}, parity skipped")

    total = problems + const_problems + parity_problems
    print()
    if total:
        print(f"DRIFT: {len(total)} problem(s).")
        return 1
    print("IN STEP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
