#!/usr/bin/env python3
"""Parity and behaviour vectors for the transmit recipe.

Replaces test_send_times.py, which held the factory's ``send_times_used``
reader in step with HAIR's. That field is gone: hair-wig/3 moved the recipe
onto the signal, so there is no longer a fitting field to read and no
aggregate to agree about.

What replaced it is a harder contract, and this file exists because of that.
``row_digest`` is published as reproducible byte for byte by any external
verifier, and the factory is the external verifier that matters most. The
digest is what a signature covers, so a factory that computed it differently
would not fail loudly -- it would quietly decide that valid attestations do
not match, or worse, that invalid ones do.

The factory therefore does not reimplement the digest. It calls HAIR's. This
file proves that decision is still true (nobody has quietly added a local
copy), pins the layout against hand-computed vectors so a change in HAIR is
caught here rather than in production, and checks the recipe reader's own
clamping behaviour.

    .venv/bin/python verify/test_recipe.py
    .venv/bin/python verify/test_recipe.py --hair /path/to/HAIR

Exit 0 means agreement.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_wig import (  # noqa: E402
    DEFAULT_HAIR,
    DITTO_COUNT_MAX,
    SEND_COUNT_MAX,
    SEND_COUNT_MIN,
    Hair,
    Recipe,
    read_default_send_count,
    read_recipe,
)

# A real Pronto from the candle wig, and one normalized differently on purpose:
# the digest is defined over the NORMALIZED form, so a file that spells the
# same code with odd whitespace or upper case hex has to produce the same
# digest. If it does not, two honest people fitting the same device get
# different digests and neither one's claim covers the other's row.
PRONTO = (
    "0000 006D 000C 0000 001C 0025 003B 0046 001A 0022 001E 0022 001E 0022 "
    "001E 0022 003E 0023 001D 0023 001D 0022 001E 0022 001E 0045 001D 0270"
)
PRONTO_MESSY = PRONTO.upper().replace(" ", "   ")


def _expected(pronto: str, ditto: int, bypass: bool, normalized: str) -> str:
    """The contract, spelled out here rather than imported.

    Deliberately duplicated from HAIR's docstring:
    ``sha256(normalized_pronto + "|d<ditto>" + "|b<0|1>")`` truncated to 16 hex
    characters. This is the one place the factory writes the layout down, and
    it is a test rather than a code path precisely so it can never be used by
    accident.
    """
    recipe = f"{normalized}|d{int(ditto)}|b{1 if bypass else 0}"
    return hashlib.sha256(recipe.encode("utf-8")).hexdigest()[:16]


# (send_count, ditto_count, bypass_protocol) -> what read_recipe should make
# of it. The send count is clamped 1..10, the ditto 0..20, and anything that
# is not a whole number falls back rather than being coerced.
RECIPE_VECTORS: list[tuple[Any, Any, Any, Recipe]] = [
    (1, 0, False, Recipe(1, 0, False)),
    (3, 1, False, Recipe(3, 1, False)),
    (10, 20, True, Recipe(10, 20, True)),
    # Clamping. A signature makes a value tamper evident, not sane.
    (0, 0, False, Recipe(1, 0, False)),
    (-5, -5, False, Recipe(1, 0, False)),
    (1000, 1000, False, Recipe(10, 20, False)),
    # bool is an int subclass and must not read as 1 / 0.
    (True, 0, False, Recipe(1, 0, False)),
    (2, True, False, Recipe(2, 0, False)),
    # Garbage in a numeric field claims nothing.
    ("3", 0, False, Recipe(1, 0, False)),
    (None, None, None, Recipe(1, 0, False)),
    (3.0, 1.0, False, Recipe(1, 0, False)),
    # bypass is a flag: anything truthy is a bypass, because a file saying
    # "yes" in some other spelling still means the encoder is out.
    (1, 0, 1, Recipe(1, 0, True)),
    (1, 0, "", Recipe(1, 0, False)),
]


class _Signal:
    """The three attributes read_recipe reads. Not HAIR's WigSignal."""

    def __init__(self, send: Any, ditto: Any, bypass: Any) -> None:
        self.send_count = send
        self.ditto_count = ditto
        self.bypass_protocol = bypass


def check_behaviour() -> list[str]:
    """The recipe reader on its own terms."""
    problems: list[str] = []
    for send, ditto, bypass, want in RECIPE_VECTORS:
        got = read_recipe(_Signal(send, ditto, bypass))
        if got != want:
            problems.append(
                f"({send!r}, {ditto!r}, {bypass!r}): read {got}, wanted {want}"
            )

    # The statements the model turns on, asserted separately because
    # collapsing them is the mistake this file exists to catch.
    if read_recipe(_Signal(1, 0, False)).plain is not True:
        problems.append("a plain row must report itself as plain")
    if read_recipe(_Signal(1, 1, False)).plain is not False:
        problems.append("one ditto is not a plain row: it changes the waveform")
    if read_recipe(_Signal(1, 0, True)).plain is not False:
        problems.append("a bypass is not a plain row")
    if SEND_COUNT_MIN != 1:
        problems.append(f"the send floor moved to {SEND_COUNT_MIN}")

    # A missing attribute is a signal from an older parse, and zero dittos is
    # the right reading: hair-wig/3 writes the field always, so its absence
    # means the file predates the field rather than asking for something.
    bare = read_recipe(object())
    if bare != Recipe(1, 0, False):
        problems.append(f"a signal with no recipe attributes read as {bare}")
    return problems


def check_parity(hair_root: Path) -> tuple[list[str], str, bool]:
    """HAIR's digest against the written contract, and against itself."""
    hair = Hair(hair_root)
    wf = hair.wig_format
    problems: list[str] = []

    normalized = wf.normalized_pronto(PRONTO)
    if normalized != normalized.lower():
        problems.append("normalized_pronto returned upper case hex")
    if wf.normalized_pronto(PRONTO_MESSY) != normalized:
        problems.append(
            "the same code spelled with different whitespace and case "
            "normalizes differently, so two fitters would produce two digests"
        )

    for ditto in (0, 1, 2, 20):
        for bypass in (False, True):
            got = wf.row_digest(PRONTO, ditto, bypass)
            want = _expected(PRONTO, ditto, bypass, normalized)
            if got != want:
                problems.append(
                    f"row_digest(ditto={ditto}, bypass={bypass}) is {got}, "
                    f"the published layout gives {want}"
                )
            if len(got) != 16:
                problems.append(f"row_digest returned {len(got)} chars, not 16")

    # The two exclusions, each asserted by demonstration rather than by
    # reading the docstring. Alias is not an input at all, and the send count
    # must not change the digest -- two people proving the same codes at three
    # and five sends are proving the same thing.
    a = wf.row_digest(PRONTO, 1, False)
    b = wf.row_digest(PRONTO, 1, False)
    if a != b:
        problems.append("row_digest is not deterministic")
    if wf.row_digest(PRONTO, 1, False) == wf.row_digest(PRONTO, 2, False):
        problems.append("the ditto count does not change the digest, but must")
    if wf.row_digest(PRONTO, 0, False) == wf.row_digest(PRONTO, 0, True):
        problems.append("the bypass flag does not change the digest, but must")

    class _Sig:
        alias = "On"
        pronto = PRONTO
        ditto_count = 1
        bypass_protocol = False
        send_count = 3

    class _SigRenamed(_Sig):
        alias = "Power"
        send_count = 9

    if wf.signal_row_digest(_Sig()) != wf.signal_row_digest(_SigRenamed()):
        problems.append(
            "renaming a row or changing its send count changed its digest. "
            "Either would orphan every claim about it on a rename, which is "
            "exactly what the digest was defined to survive."
        )

    # And the decision this file is really guarding: no local copy.
    source = (Path(__file__).resolve().parent / "verify_wig.py").read_text(
        encoding="utf-8"
    )
    if "hashlib" in source:
        problems.append(
            "verify_wig.py imports hashlib. The digest is HAIR's to compute "
            "and a second implementation is how the contract forks. If this "
            "is a deliberate new use, say so here."
        )

    their_send = getattr(wf, "MAX_SEND_COUNT", None)
    if their_send is not None and int(their_send) != SEND_COUNT_MAX:
        problems.append(
            f"send ceiling drift: HAIR clamps to {their_send}, the factory "
            f"clamps to {SEND_COUNT_MAX}"
        )
    their_ditto = getattr(wf, "MAX_DITTO_COUNT", None)
    if their_ditto is not None and int(their_ditto) != DITTO_COUNT_MAX:
        problems.append(
            f"ditto ceiling drift: HAIR clamps to {their_ditto}, the factory "
            f"clamps to {DITTO_COUNT_MAX}"
        )
    return (
        problems,
        f"digest layout and both exclusions hold against HAIR {hair.version}",
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
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    args = parser.parse_args(argv)

    print("transmit recipe: behaviour and digest parity\n")

    problems = check_behaviour()
    for line in problems:
        print(f"  FAIL  behaviour: {line}")
    if not problems:
        print(f"  PASS  behaviour: {len(RECIPE_VECTORS)} vectors read as expected")

    const_problems = check_const_parsing()
    for line in const_problems:
        print(f"  FAIL  const.py: {line}")
    if not const_problems:
        print("  PASS  const.py parses without importing")

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
