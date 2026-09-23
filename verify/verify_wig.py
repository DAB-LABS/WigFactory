#!/usr/bin/env python3
"""The self-verification gate.

An LLM writing an IR codec will be wrong some of the time. This script is
the machine that catches it before anything is published.

It works because HAIR owns protocol decoders that never saw the generated
code. They are an independent witness, and the gate uses them in both
directions:

  Forward.  The generated codebook encodes a command. HAIR decodes the
            result. The identity read back must equal the identity HAIR
            reads from the wig's own captured Pronto.

  Reverse.  The wig's captured Pronto goes through the decoder vendored
            into the generated integration. It must produce that same
            identity.

  Coverage. Every wig alias has exactly one codebook entry, and every
            codebook entry traces to exactly one wig alias.

There is one further pair of checks that is not about the codec at all. From
hair-wig/3 (HAIR 0.9.5) a wig STATES the transmit recipe for every row: how
many times to send the blob, how many repeat frames the encoder appends inside
one transmission, and whether to bypass the encoder entirely. A claim binds
that recipe by digest. So the generated integration has to reproduce it, and
the gate checks both halves: the shipped send-count default must not sit below
what the wig asks for, and any row asking for dittos or a bypass must be
expressed by the integration rather than silently dropped. A codec can be
perfectly correct and still put a different waveform on the air.

Press state (the RC-5 toggle bit and its relatives) is excluded on both
sides, because a toggle records which press it was and not which button.
That exclusion is HAIR's, not ours: identities are compared on the decoded
fingerprint, which HAIR already defines with press state left out.

Usage:
    verify_wig.py --wig WIG [--gate-only]
    verify_wig.py --wig WIG --integration PATH [--json]

Exit code 0 means every check that ran passed. Anything else is a refusal.
"""

from __future__ import annotations

import argparse
import ast
import collections
import importlib
import importlib.metadata
import importlib.util
import json
import sys
import types
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_climate import (  # noqa: E402
    check_climate_integration,
    find_climate_component,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HAIR = REPO_ROOT / "reference" / "HAIR"
DEFAULT_SHOP = REPO_ROOT / "reference" / "WigShop"

# How many independent accounts the factory considers "widely proven", used
# only to phrase the report. NOT a bar: the formal three-fittings rule was
# retired on 2026-08-04, following HAIR retiring it from the format on
# 2026-08-02. The shop admits perfect fits only, so arriving wigs are already
# proven by somebody; how many people is a judgment, not a threshold.
WIDELY_PROVEN_ACCOUNTS = 3

# The bounds every reader clamps a send count to, matching HAIR's
# const.MAX_SEND_COUNT. One frame is the floor because zero sends is not a
# measurement, and ten is the ceiling because past that the airtime costs more
# than the reliability buys.
SEND_COUNT_MIN = 1
SEND_COUNT_MAX = 10

# HAIR's const.MAX_DITTO_COUNT. Repeat frames the encoder appends inside one
# transmission, which is a different thing from sending the whole blob again.
DITTO_COUNT_MAX = 20

# hair-wig/3 (HAIR 0.9.5, the Fitting Room) moved the transmit recipe onto the
# signal and attestation onto per-row digests. Before it, a fitting reported
# ``send_times_used``: how many presses THAT FITTER'S ROOM needed, which the
# factory aggregated by maximum across fitters. After it, the wig states what
# the row needs and there is nothing to aggregate. The old field is gone from
# HAIR entirely, so a reader still looking for it finds nothing and, worse,
# reports the silence as "these fittings predate 0.9.0".
RECIPE_MAJOR = 3

# The names of the HAIR functions this gate cannot work without. Checked at
# construction so a stale reference checkout produces one sentence telling you
# to update it, rather than an AttributeError forty frames down. That is not
# hypothetical: 0.9.5 removed ``wig_fitting.fitting_rows`` and every entry
# point in this repo died on the traceback rather than refusing.
# HAIR's comb check names, from wig_comb.py. Spelled out because the gate
# reasons about WHICH classes it can independently reproduce, and a typo in a
# string key would silently move a class into the "cannot see" bucket, which
# reads as caution and is actually blindness.
COMB_MALFORMED = "malformed"
COMB_FRAME_DISAGREEMENT = "frame-disagreement"
COMB_FIELD_MISMATCH = "field-mismatch"
COMB_FRAME_INTEGRITY = "frame-integrity"
COMB_STRAY_BURST = "stray-burst"
COMB_FRAME_SHAPE = "frame-shape"
COMB_DUPLICATED_NEIGHBOUR = "duplicated-neighbour"
COMB_MISSING_CELL = "missing-cell"
COMB_STRAY_CELL = "stray-cell"
COMB_COORDINATE_COLLISION = "coordinate-collision"
COMB_DUPLICATE_LABELS = "duplicate-labels"
COMB_BYPASS_WITH_DITTOS = "bypass-with-dittos"
COMB_RAMP_DITTOS = "ramp-dittos"

# Every class HAIR's comb can report. test_recipe.py fails the moment HAIR
# grows one this list does not name, because an unnamed class is one the gate
# cannot talk about, and silence about a finding reads as approval.
COMB_CLASSES = frozenset({
    COMB_MALFORMED, COMB_FRAME_DISAGREEMENT, COMB_FIELD_MISMATCH,
    COMB_FRAME_INTEGRITY, COMB_STRAY_BURST, COMB_FRAME_SHAPE,
    COMB_DUPLICATED_NEIGHBOUR, COMB_MISSING_CELL, COMB_STRAY_CELL,
    COMB_COORDINATE_COLLISION, COMB_DUPLICATE_LABELS, COMB_BYPASS_WITH_DITTOS,
    COMB_RAMP_DITTOS,
})

# The classes where the state a code sends is not the state it claims. The
# rest are about how a capture looks; these are about what the device does.
COMB_WRONG_STATE = frozenset({COMB_DUPLICATED_NEIGHBOUR, COMB_FIELD_MISMATCH})

# How honest a repair record is about the room it was proved in. Written by
# HAIR 0.14.0 and later onto each mended code, outside every hash.
REPAIR_KEY = "hair_repair"
REPAIR_TIERS = ("air-tested", "rule-derived", "accepted")

REQUIRED_HAIR_API = {
    "wig_format": (
        "wig_row_digests", "signal_row_digest", "row_digest", "claims_of",
        "coverage", "perfect_by", "parse_claims_bundle", "is_claims_bundle",
        "is_legacy_fitting", "wig_content_hash", "cells_content_hash",
        "cell_key",
    ),
    "wig_fitting": ("bundle_is_complete",),
    "wig_climate": ("dimension_checklist", "resolve_cell"),
    # A climate integration replays captured codes, and has to put exactly
    # what HAIR would put on the wire, terminator included (GH #98).
    "ir_command": ("ProntoCommand", "TerminatedCommand", "TERMINATOR_SPACE_US"),
    # The live comb (HAIR 0.9.1, field tier from 0.12.0). Read on every run
    # rather than trusting the receipt a file carries.
    "wig_comb": ("comb_wig",),
    # Decode trust (HAIR 0.14.2): does a label account for its whole
    # capture. The factory rebuilds codes from labels, so this is the
    # difference between transmitting what was fitted and something else.
    "protocol_decode": ("try_decode_identity", "decode_coverage"),
}

# How the gate exits, so a caller can tell a verdict from a breakdown.
#
# REFUSED is a judgment about somebody else's data: this wig cannot be built
# from. ENVIRONMENT means no judgment was reached at all, because the HAIR
# checkout is missing or too old, a dependency is not installed, or the gate
# itself crashed. CI treats the two differently and has to be able to, because
# on 2026-08-17 a wig refusal and a factory bug were the same red X, and for a
# month after that a missing dependency hid behind the same colour as a bad wig.
EXIT_PASSED = 0
EXIT_REFUSED = 1
EXIT_ENVIRONMENT = 3


def environment_exit(message: str) -> SystemExit:
    """Say why no verdict was reached, and return the exit to raise.

    Printed here rather than carried on the exception, because a SystemExit
    with an integer code exits silently and the message is the useful part.
    """
    print(f"no verdict: {message}", file=sys.stderr)
    return SystemExit(EXIT_ENVIRONMENT)


# ---------------------------------------------------------------------------
# Contributor identity
# ---------------------------------------------------------------------------


def github_key(value: object) -> str | None:
    """The canonical form of a GitHub handle, for comparison only.

    People type this field by hand, so one account arrives as ``dab``,
    ``@dab``, ``DAB`` and ``github.com/dab``. Compared raw, one person on two
    installs reads as two distinct contributors, which is precisely what the
    three-distinct-handles gate exists to prevent. The first two wigs that
    ever existed already disagree with each other this way.

    This never rewrites a file. A fitting's ed25519 signature covers its own
    contents including ``github``, so normalizing on disk would invalidate the
    signature and break the shop's immutability rule at the same time. The
    canonical form is something to compare with, never something to store.

    Kept deliberately in step with ``github_key()`` in WigShop's
    ``tools/validate_wigs.py``. If the two drift, the shop and the factory
    will disagree about who contributed what.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "www.github.com/",
        "github.com/",
    ):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.lstrip("@").strip()
    # A pasted URL carries more than the account: a repo path
    # (github.com/name/repo) or a query (github.com/name?tab=stars). Keep the
    # first segment only. Without this the key comes back as "name/repo",
    # which is not merely useless, it is wrong: it makes one account look like
    # a different contributor from the same account typed plainly, which is
    # the exact failure this function exists to prevent.
    for sep in ("/", "?", "#"):
        text = text.split(sep, 1)[0]
    return text.strip().casefold() or None


#: What HAIR names a download and therefore what lands in the shop:
#: ``<brand>-<kind>-<model>-perfect-fit.wig.json``. The suffix records the
#: fitting tier at the moment of download and is a courtesy to whoever has
#: the file in their Downloads folder, nothing more. The shop never reads a
#: tier from a filename either: claims are the evidence, and a name that
#: could promote a file by being edited would defeat signed per-row claims.
#:
#: It must not reach a repository name. ``fable-fan-ft-9000-perfect-fit-ir``
#: would bake a transient label into a slug, a domain, a config entry and a
#: device registry entry, none of which can be changed later without taking
#: somebody's install down. There is one tier now, so the stem underneath is
#: stable and stripping it is safe.
TIER_SUFFIXES = ("-perfect-fit",)


def device_stem(name: str) -> str:
    """The ``<brand>-<kind>-<model>`` part of a wig filename, tier removed."""
    stem = Path(name).name.removesuffix(".json").removesuffix(".wig")
    for suffix in TIER_SUFFIXES:
        if stem.endswith(suffix) and stem != suffix:
            return stem[: -len(suffix)]
    return stem


def wig_slug(wig_path: Path) -> str:
    """The shop slug a wig file corresponds to, without its tier suffix."""
    return device_stem(wig_path.name)


# ---------------------------------------------------------------------------
# The transmit recipe
# ---------------------------------------------------------------------------


def _fittings(count: int) -> str:
    """Pluralize a fitting count. Gate output gets read by people."""
    return f"{count} fitting" if count == 1 else f"{count} fittings"


@dataclass(frozen=True)
class Recipe:
    """What one row asks to have put on the air.

    The three fields HAIR's ``row_digest`` binds, minus the Pronto itself:
    everything here changes the waveform, which is why a claim covers it. A
    fitter who proved a row proved THIS recipe against THOSE bytes, so an
    integration that ships different numbers is shipping something nobody
    attested, however correct its codec is.
    """

    send_count: int
    ditto_count: int
    bypass_protocol: bool

    @property
    def plain(self) -> bool:
        """True when this row needs nothing the old model could not express."""
        return self.ditto_count == 0 and not self.bypass_protocol

    def describe(self) -> str:
        parts = [f"send x{self.send_count}"]
        if self.ditto_count:
            parts.append(f"ditto x{self.ditto_count}")
        if self.bypass_protocol:
            parts.append("raw (encoder bypassed)")
        return ", ".join(parts)


def read_recipe(signal: Any) -> Recipe:
    """The recipe a parsed signal states, clamped.

    Clamped on read because a signature makes a value tamper evident, not
    sane: a bundle can be perfectly signed over a row carrying 1000 sends. The
    clamp is the factory's, applied to what it will act on; it deliberately
    does NOT rewrite the wig, because the digest binds the stored value and
    quietly normalizing it here would put the gate and the claim into
    disagreement about what was proven.

    ``bool`` is an ``int`` subclass, so a ``True`` arriving in a numeric field
    would otherwise read as 1. That is garbage, not a measurement.
    """

    def whole(value: Any, low: int, high: int, fallback: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return fallback
        return max(low, min(value, high))

    return Recipe(
        send_count=whole(
            getattr(signal, "send_count", 1),
            SEND_COUNT_MIN, SEND_COUNT_MAX, SEND_COUNT_MIN,
        ),
        # Zero is the floor and the default: no repeat frame. Unlike send
        # count, one ditto is a real and different waveform, so there is no
        # "absent is not 1" problem here -- absent IS zero, and hair-wig/3
        # writes the field always rather than only when set.
        ditto_count=whole(
            getattr(signal, "ditto_count", 0), 0, DITTO_COUNT_MAX, 0
        ),
        bypass_protocol=bool(getattr(signal, "bypass_protocol", False)),
    )


def wig_recipes(wig: Any) -> dict[str, Recipe]:
    """Every flat row's recipe, keyed by alias, in file order."""
    return {signal.alias: read_recipe(signal) for signal in wig.signals}


def read_default_send_count(component_dir: Path) -> dict[str, int]:
    """Read the send-count constants out of a generated ``const.py``.

    Parsed, not imported. ``const.py`` in a generated integration is plain
    module level assignments, and reading it with ``ast`` means the gate can
    check the number a user will actually get without importing anything that
    might reach for Home Assistant.
    """
    found: dict[str, int] = {}
    path = component_dir / "const.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return found
    wanted = {"DEFAULT_SEND_COUNT", "MIN_SEND_COUNT", "MAX_SEND_COUNT"}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in wanted:
                continue
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
            ):
                found[target.id] = value.value
    return found


# ---------------------------------------------------------------------------
# The Wig Shop clone
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str | None:
    """Run a read-only git command in ``repo``, or None if it cannot."""
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def shop_provenance(shop: Path) -> dict[str, str] | None:
    """The shop clone's commit, so a build can say what it read.

    Fittings accumulate over time, which makes "three distinct accounts" a
    claim about a moment rather than a permanent fact. Recording the commit
    turns that into something anybody can reproduce: check out this SHA and
    you see exactly what the factory saw. Without it, a reader who goes to
    look and finds five fittings where the README says one has no way to tell
    whether the wig gained fittings or the stamp was wrong.
    """
    if not (shop / ".git").exists():
        return None
    sha = _git(shop, "rev-parse", "HEAD")
    if sha is None:
        return None
    return {
        "sha": sha,
        "short": sha[:7],
        "date": _git(shop, "log", "-1", "--format=%cs") or "unknown",
    }


def resolve_shop_wig(shop: Path, slug: str) -> tuple[Path | None, list[str]]:
    """Find ``<slug>.wig.json`` under the shop clone's brand folders.

    Returns the path and, when nothing matched, the slugs that do exist so the
    error can be useful rather than merely correct.
    """
    wigs_dir = shop / "wigs"
    if not wigs_dir.is_dir():
        return None, []
    available = sorted(
        device_stem(p.name) for p in wigs_dir.glob("*/*.wig.json")
    )
    # Matched on the DEVICE stem, not the literal filename, so somebody can
    # name the device rather than remember which tier suffix the file landed
    # with. Both spellings resolve to the same wig.
    wanted = device_stem(slug)
    matches = sorted(
        p for p in wigs_dir.glob("*/*.wig.json") if device_stem(p.name) == wanted
    )
    if len(matches) == 1:
        return matches[0], available
    return None, available


def locate_wig(
    given: str, shop: Path, report: Report
) -> tuple[Path | None, dict[str, str] | None]:
    """Resolve ``--wig`` to a file, from disk or from the shop clone.

    A path that exists is used as given, and nothing is claimed about where it
    came from. Anything else is treated as a shop slug, which is the ruled
    input path: the factory reads the same merged file every contributor sees,
    rather than somebody's local export.
    """
    # is_file, not exists. The generated output folder is named after the slug
    # by convention, so `--wig sanmli-candles-th05` run from the repo root
    # matches a directory before it ever reaches the shop.
    direct = Path(given)
    if direct.is_file():
        provenance = None
        try:
            inside_shop = direct.resolve().is_relative_to(shop)
        except (OSError, ValueError):
            inside_shop = False
        if inside_shop:
            provenance = shop_provenance(shop)
        return direct, provenance

    if not shop.exists():
        report.fail(
            f"'{given}' is not a file, and there is no Wig Shop clone at "
            f"{shop} to resolve it as a slug. Run ./setup.sh first."
        )
        return None, None

    found, available = resolve_shop_wig(shop, given)
    if found is None:
        listing = ", ".join(available) if available else "none yet"
        report.fail(
            f"'{given}' is not a file and does not name exactly one wig in the "
            f"shop. Available: {listing}"
        )
        return None, None

    provenance = shop_provenance(shop)
    if provenance is not None:
        report.ok(
            f"resolved from the Wig Shop at {provenance['short']} "
            f"({provenance['date']}): {found.relative_to(shop)}"
        )
        report.note(
            "the shop clone is a snapshot. Fittings accumulate, so run "
            "./setup.sh to refresh before a build that will be published."
        )
    return found, provenance


# ---------------------------------------------------------------------------
# Loading HAIR without Home Assistant
# ---------------------------------------------------------------------------


class Hair:
    """HAIR's decode and format modules, imported without Home Assistant.

    ``custom_components/hair/__init__.py`` pulls in Home Assistant, which we
    do not have and do not need. The modules the gate uses are deliberately
    free of that dependency, so the package objects are constructed by hand
    and the submodules imported into them. Relative imports inside HAIR
    resolve normally against the ``__path__`` set here.
    """

    def __init__(self, hair_root: Path) -> None:
        pkg_root = hair_root / "custom_components"
        hair_pkg = pkg_root / "hair"
        if not (hair_pkg / "protocol_decode.py").is_file():
            raise environment_exit(
                f"HAIR not found at {hair_root}. Run ./setup.sh first, or "
                f"pass --hair with the path to a HAIR checkout."
            )

        # Upstream decoders are REQUIRED, not a smaller-but-workable mode.
        # HAIR has no local decoder for NEC, the most common consumer
        # protocol there is, so without upstream every NEC wig reads "does
        # not decode to any known protocol". That is a false statement about
        # a good wig, and it happened: on 2026-09-22 the Winix 5500 refused
        # on Python 3.12, where upstream cannot be installed, and passed on
        # 3.14. An environment problem must not be reported as a wig defect.
        try:
            self.upstream_version: str = importlib.metadata.version(
                "infrared-protocols"
            )
            importlib.import_module("infrared_protocols")
        except Exception as err:  # noqa: BLE001 - any failure means absent
            raise environment_exit(
                f"upstream infrared-protocols is not importable ({err!r}). "
                f"HAIR has no local decoder for NEC and several other "
                f"protocols, so without it good wigs would be reported as "
                f"undecodable. Install verify/requirements.txt on Python 3.13 "
                f"or newer (./setup.sh does this)."
            ) from None

        for name, path in (
            ("custom_components", pkg_root),
            ("custom_components.hair", hair_pkg),
        ):
            if name not in sys.modules:
                module = types.ModuleType(name)
                module.__path__ = [str(path)]  # type: ignore[attr-defined]
                sys.modules[name] = module

        self.root = hair_root
        self.protocol_decode = importlib.import_module(
            "custom_components.hair.protocol_decode"
        )
        self.ir_command = importlib.import_module(
            "custom_components.hair.ir_command"
        )
        self.wig_format = importlib.import_module(
            "custom_components.hair.wig_format"
        )
        self.fitting_signing = importlib.import_module(
            "custom_components.hair.fitting_signing"
        )
        # REQUIRED from 0.9.5, where it used to be optional. `wig_fitting`
        # owns `bundle_is_complete`, and completeness is not something the
        # factory is entitled to a second opinion about: it is the difference
        # between "somebody proved this" and "somebody proved most of this".
        self.wig_fitting: Any | None
        try:
            self.wig_fitting = importlib.import_module(
                "custom_components.hair.wig_fitting"
            )
        except BaseException:  # noqa: BLE001 - reported by _require_api
            self.wig_fitting = None

        # Matrix wigs. `wig_climate` owns the dimension checklist, which is
        # what a matrix fitting actually walks, and `cell_key` owns the key
        # format. Both are HAIR's to define, and the factory reading a lattice
        # by its own rules is how the two ends stop agreeing about what was
        # proven.
        self.wig_climate: Any | None
        try:
            self.wig_climate = importlib.import_module(
                "custom_components.hair.wig_climate"
            )
        except BaseException:  # noqa: BLE001
            self.wig_climate = None

        self.wig_comb: Any | None
        try:
            self.wig_comb = importlib.import_module(
                "custom_components.hair.wig_comb"
            )
        except BaseException:  # noqa: BLE001 - reported by _require_api
            self.wig_comb = None

        # Optional: only used to tell whether an attestation's field-map
        # version still matches the map HAIR reads the codes with today.
        self.field_readers: Any | None
        try:
            self.field_readers = importlib.import_module(
                "custom_components.hair.field_readers"
            )
        except BaseException:  # noqa: BLE001
            self.field_readers = None

        # LAST. Every optional import has to have been attempted before the
        # audit runs, or the audit reports a module that loads perfectly well
        # as missing, which is a confident wrong answer.
        self._require_api()

    def _require_api(self) -> None:
        """Refuse a HAIR checkout too old to answer the questions we ask.

        A missing name here is not a degraded mode, it is a different format
        era, and guessing across one is how a gate reports a green run about
        rules it never applied. The failure this replaces was real: HAIR 0.9.5
        removed ``wig_fitting.fitting_rows`` and the gate died on an
        AttributeError inside a set comprehension, which reads as a factory
        bug rather than as "your reference clone is stale".
        """
        missing: list[str] = []
        for module_name, names in REQUIRED_HAIR_API.items():
            module = getattr(self, module_name, None)
            if module is None:
                missing.append(f"{module_name} (whole module)")
                continue
            missing += [
                f"{module_name}.{name}"
                for name in names
                if not hasattr(module, name)
            ]
        if not missing:
            return
        raise environment_exit(
            f"the HAIR checkout at {self.root} is version {self.version} and "
            f"does not provide: {', '.join(missing)}.\n"
            f"The factory reads the hair-wig/{RECIPE_MAJOR} claims model, "
            f"which arrived in HAIR 0.9.5. Run ./setup.sh to refresh the "
            f"reference clones, or pass --hair with a newer checkout."
        )

    @property
    def version(self) -> str:
        manifest = self.root / "custom_components" / "hair" / "manifest.json"
        try:
            return json.loads(manifest.read_text())["version"]
        except Exception:
            return "unknown"

    def identity(self, raw_timings: list[int]) -> Any | None:
        """Decode signed microsecond timings to a HAIR identity."""
        return self.protocol_decode.try_decode_identity(raw_timings)

    def covers_capture(self, raw_timings: list[int]) -> bool | None:
        """Does the decoded label account for the whole capture?

        True, False, or None when HAIR cannot say, which is HAIR's own
        answer for a decoder whose frame accounting it cannot verify.
        """
        return self.protocol_decode.decode_coverage(raw_timings)

    def comb(self, wig: Any) -> Any:
        """HAIR's comb, run now, on these bytes."""
        return self.wig_comb.comb_wig(wig)

    def field_map_version(self, protocol_id: str | None) -> str | None:
        """The content version of the field map HAIR reads a family with."""
        if not protocol_id or self.field_readers is None:
            return None
        try:
            for field_map in self.field_readers.library():
                if field_map.protocol_id == protocol_id:
                    return field_map.version
        except Exception:  # noqa: BLE001 - absence is the honest answer
            return None
        return None

    def timings_from_pronto(self, pronto: str) -> list[int] | None:
        """Convert Pronto hex to signed microsecond timings."""
        try:
            command = self.ir_command.ProntoCommand(pronto)
        except (ValueError, IndexError):
            return None
        raw = command.get_raw_timings()
        return raw or None

    def content_hash(self, wig: Any) -> str:
        """The wig's canonical hash: signals for v1, cells for a matrix.

        NO LONGER AN ATTESTATION TARGET. From hair-wig/3 nothing signs this
        and no file carries it; it survives as the deduplication identity,
        which is exactly what the factory still wants it for -- a stable name
        for "the same codes" to record in a README and a commit message.
        """
        return self.wig_format.wig_content_hash(wig)

    def row_digests(self, wig: Any) -> list[str]:
        """Every flat row's digest, in file order. Empty for a matrix wig.

        THE binding target from 0.9.5 on:
        ``sha256(normalized_pronto + "|d<ditto>" + "|b<0|1>")[:16]``. The
        factory calls HAIR's implementation rather than reproducing the
        layout, because two implementations of one contract is how the
        contract forks.
        """
        return self.wig_format.wig_row_digests(wig)

    def signal_row_digest(self, signal: Any) -> str:
        """One flat signal's digest."""
        return self.wig_format.signal_row_digest(signal)

    def claims(self, wig: Any) -> list[Any]:
        """Every claims bundle on a wig. Legacy fittings are skipped."""
        return self.wig_format.claims_of(wig)

    def bundle_complete(
        self, bundle: Any, wig: Any, digests: list[str] | None = None
    ) -> bool:
        """Did one bundle claim everything there was to claim?"""
        return self.wig_fitting.bundle_is_complete(bundle, wig, digests)

    def covered(self, bundles: list[Any], digests: list[str]) -> set[str]:
        """Which rows anybody claimed worked, pooled."""
        return self.wig_format.coverage(bundles, digests)

    def cell_key(self, cell: Any) -> str:
        """HAIR's cell key, `cool/auto/23` shaped. Never reimplement this."""
        return self.wig_format.cell_key(cell)

    def cells_hash(self, matrix: Any) -> str:
        """The lattice hash a matrix bundle pins with ``cells_hash``."""
        return self.wig_format.cells_content_hash(matrix)

    def dimension_checklist(self, matrix: Any) -> list[Any]:
        """The deterministic sample of a lattice a fitter is actually shown."""
        return self.wig_climate.dimension_checklist(matrix)

    def row_digest(self, pronto: str, ditto: int = 0, bypass: bool = False) -> str:
        """One row's digest from its parts, for rows that are not signals."""
        return self.wig_format.row_digest(pronto, ditto, bypass)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """What the gate found. Empty ``failures`` is the only pass."""

    checks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def ok(self, message: str) -> None:
        self.checks.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    @property
    def passed(self) -> bool:
        return not self.failures


# ---------------------------------------------------------------------------
# Step 2: the input gate
# ---------------------------------------------------------------------------


def run_input_gate(
    hair: Hair,
    wig_path: Path,
    report: Report,
    require_handles: int | None = None,
) -> Any | None:
    """Enforce the input contract. Returns the parsed wig, or None."""
    try:
        text = wig_path.read_text(encoding="utf-8")
    except OSError as err:
        report.fail(f"cannot read {wig_path}: {err}")
        return None

    result = hair.wig_format.parse_wig(text)
    if not result.ok:
        for error in result.errors:
            report.fail(f"wig does not parse: {error}")
        return None
    wig = result.wig
    report.ok(f"parses as a wig through HAIR {hair.version}")

    matrix = getattr(wig, "climate", None)
    if matrix is None and not wig.signals:
        report.fail("wig has neither signals nor a climate block")
        return None

    report.facts["name"] = wig.name
    report.facts["brand"] = wig.brand
    report.facts["model"] = wig.model
    report.facts["kind"] = wig.kind
    report.facts["identifiers"] = dict(wig.identifiers or {})
    report.facts["signal_count"] = len(wig.signals)
    report.facts["hair_version"] = hair.version
    report.facts["infrared_protocols"] = hair.upstream_version
    # Ancestry (HAIR 0.9.7). Outside every canonical form and every digest,
    # so it can never move an identity or disturb a claim. Recorded because a
    # content change is now a NEW wig at the SAME filename, and this list is
    # the only thing that distinguishes a legitimate successor from an
    # unrelated wig that happens to be named the same.
    ancestry = list(getattr(wig, "supersedes", []) or [])
    if ancestry:
        report.facts["supersedes"] = ancestry
    report.facts["shape"] = "matrix" if matrix is not None else "signals"

    aliases = [signal.alias for signal in wig.signals]
    if len(set(aliases)) != len(aliases):
        duplicates = sorted({a for a in aliases if aliases.count(a) > 1})
        report.fail(f"duplicate aliases in the wig: {', '.join(duplicates)}")

    _check_carrierless(hair, wig, report)

    if matrix is not None:
        _check_extras(matrix, report)
        check_matrix(hair, wig, matrix, report)

    live = check_comb(hair, wig, report)
    check_repairs(hair, wig, live, report)

    # BEFORE the fittings, and unconditionally. The recipe is a property of
    # the wig: a row asking for a waveform nothing can produce is wrong even
    # if every fitting on the file is broken too, and running this inside
    # _check_fittings meant its early return swallowed the check entirely.
    _check_recipe(hair, wig, report)

    _check_fittings(hair, wig, report, require_handles)
    return wig


def _verify_signature(hair: Hair, entry: dict[str, Any]) -> str | None:
    """Verify one fitting's signature, never trusting a broken backend.

    ``verify_fitting`` returns "valid", "invalid" or None (unsigned). A
    cryptography backend that is missing or mis-installed can raise, and some
    of those failures arrive as BaseException rather than Exception. A gate
    that cannot check a signature reports invalid. It never vouches blind.
    """
    try:
        return hair.fitting_signing.verify_fitting(entry)
    except BaseException:  # noqa: BLE001 - see docstring
        return "invalid"


def matrix_checklist_digests(hair: Hair, wig: Any) -> set[str] | None:
    """The dimension checklist a lattice implies, as row digests.

    DERIVED HERE, NOT ASKED FOR, and that is the whole point. HAIR's
    ``bundle_is_complete`` as shipped in 0.9.7 asks only "non-empty, and every
    row in the bundle worked". It never re-derives what the lattice implies,
    so a bundle that simply omits a dimension reads complete, and a ONE-ROW
    bundle over a two-thousand-cell lattice reads complete. Silence is not a
    claim.

    Verified against the shipped source rather than assumed. HAIR fixed its
    own ``bundle_is_complete`` in 0.9.8 (``dimension_checklist_digests``), but
    files minted by 0.9.7 installs are in the wild, so the factory still
    derives the answer instead of trusting the one it is given. The
    Wig Shop's validator reached the same conclusion independently and this
    mirrors its derivation exactly, down to the digest arguments: cells carry
    no dittos and are never bypassed, so both are fixed rather than read.

    Returns None when the checklist cannot be derived, which is a different
    thing from an empty one and is never treated as passing.
    """
    matrix = getattr(wig, "climate", None)
    if matrix is None:
        return None
    try:
        items = hair.dimension_checklist(matrix)
    except BaseException:  # noqa: BLE001 - a shape HAIR's walk cannot handle
        return None
    return {hair.row_digest(item.pronto, 0, False) for item in items}


def _check_fittings(
    hair: Hair,
    wig: Any,
    report: Report,
    require_handles: int | None = None,
) -> None:
    """Fittings must exist, cover every row, bind to this wig, and verify.

    Rewritten for hair-wig/3. The old shape asked one question of the whole
    file -- does your ``content_hash`` still match? -- and a yes covered every
    signal at once. The claims model asks it per row, which is strictly more
    honest: editing one code now orphans exactly the claims about that code
    instead of invalidating everybody's whole attestation, and a partial
    fitting can say what it actually proved rather than being discarded.

    A PRE-CLAIMS FITTING NO LONGER COUNTS. It cannot: it carries a whole-file
    hash and nothing about which rows anybody walked, so promoting one would
    mean inventing per-row evidence nobody produced. It is reported, by name,
    with what to do about it, and then ignored.
    """
    fittings = wig.extra.get("fittings")
    if not isinstance(fittings, list) or not fittings:
        report.fail(
            "wig carries no fitting. A wig without a fitting is a spreadsheet, "
            "and this factory does not take spreadsheets."
        )
        return

    # Recorded, not enforced. From hair-wig/3 nothing signs this and no file
    # carries it; it is the dedup identity and a stable thing to print.
    report.facts["content_hash"] = hair.content_hash(wig)
    report.facts["wig_id"] = getattr(wig, "wig_id", None)

    matrix = getattr(wig, "climate", None)
    digests = hair.row_digests(wig)

    # For a matrix the interesting number is the CHECKLIST, not the cell
    # count. Nobody presses two thousand buttons; the checklist is what a
    # fitter is actually shown and therefore what a claim can cover.
    checklist = matrix_checklist_digests(hair, wig) if matrix is not None else None
    if matrix is not None:
        if checklist is None:
            report.fail(
                "this lattice's dimension checklist cannot be derived, so "
                "there is no way to tell whether anybody walked it. A "
                "checklist that cannot be computed is not an empty one."
            )
            return
        report.facts["checklist_rows"] = len(checklist)
    report.facts["fitting_row_count"] = (
        len(checklist) if checklist is not None else len(digests)
    )

    complete: list[dict[str, Any]] = []
    bundles: list[Any] = []
    legacy: list[str] = []

    for index, entry in enumerate(fittings):
        label = f"fittings[{index}]"
        if not isinstance(entry, dict):
            report.fail(f"{label} is not an object")
            continue
        who = str(entry.get("handle") or entry.get("github") or "(no handle)")
        label = f"fitting by {who}"

        # Shape, never the version stamp (HAIR hard rule 6). A file can be
        # stamped /3 and still carry a pre-claims block; trusting the major
        # would let it through into a model with no reader for it.
        if hair.wig_format.is_legacy_fitting(entry):
            legacy.append(who)
            continue
        bundle = hair.wig_format.parse_claims_bundle(entry)
        if bundle is None:
            report.fail(
                f"{label} is neither a claims bundle nor a pre-claims "
                f"fitting. A bundle carries wig_id and rows; a pre-claims "
                f"fitting carries content_hash. This carries neither, so "
                f"there is no way to tell what it is attesting."
            )
            continue

        # Identity first. A bundle whose wig_id names a different wig is not
        # a stale attestation, it is somebody else's attestation, and the row
        # digests could still line up by coincidence on a shared code set.
        wig_id = getattr(wig, "wig_id", None)
        if wig_id and bundle.wig_id != wig_id:
            report.fail(
                f"{label} claims wig_id {bundle.wig_id}, but this wig is "
                f"{wig_id}. That is an attestation about a different file."
            )
            continue

        if matrix is not None:
            # A checklist samples a lattice, so the bundle has to pin the
            # lattice it sampled. Named cells_hash and never content_hash,
            # precisely so the legacy test above stays unambiguous.
            expected = hair.cells_hash(matrix)
            if bundle.cells_hash != expected:
                report.fail(
                    f"{label} pins lattice {bundle.cells_hash}, but these "
                    f"cells hash to {expected}. The lattice moved after "
                    f"somebody walked it."
                )
                continue

        unknown = [
            row.digest for row in bundle.rows
            if matrix is None and row.digest not in set(digests)
        ]
        if unknown:
            report.note(
                f"{label} claims {len(unknown)} row(s) this wig no longer "
                f"has. Orphaned by an edit, not a failure: the remaining "
                f"claims still stand."
            )

        # NOT hair.bundle_complete for a matrix: see matrix_checklist_digests.
        # A flat wig delegates to HAIR so the factory and the closet cannot
        # disagree; a matrix wig is checked against the derived checklist,
        # which is what the Wig Shop's shelf gate does.
        if checklist is not None:
            # The lattice this bundle walked was already pinned above, so what
            # is left is whether the walk was covered. Both halves of the
            # shop's bundle_is_perfect are therefore enforced, in the two
            # places each belongs.
            worked_digests = {
                row.digest for row in bundle.rows
                if row.verdict == hair.wig_format.VERDICT_WORKED
            }
            proven = checklist <= worked_digests
        else:
            proven = hair.bundle_complete(bundle, wig, digests or None)

        if not proven:
            # Against the wig's CURRENT digests. Counting the bundle's own
            # worked rows instead reported "12 of 12 claimed as working" on a
            # wig whose codes had been edited underneath it, which is exactly
            # backwards: the claims are intact and the wig moved.
            live = checklist if checklist is not None else set(digests)
            worked = sum(
                1 for row in bundle.rows
                if row.verdict == hair.wig_format.VERDICT_WORKED
                and row.digest in live
            )
            excluded = [
                f"{row.alias_at_claim or row.digest} ({row.verdict})"
                for row in bundle.rows
                if row.verdict != hair.wig_format.VERDICT_WORKED
            ]
            detail = f"; excluded: {', '.join(excluded[:4])}" if excluded else ""
            report.note(
                f"{label} is incomplete: {worked} of "
                f"{report.facts['fitting_row_count']} row(s) claimed as "
                f"working{detail}"
            )
            bundles.append(bundle)
            continue

        verdict = _verify_signature(hair, entry)
        if verdict == "invalid":
            report.fail(
                f"{label} claims a signature that does not verify. Either the "
                f"record was altered or cryptography is not installed."
            )
            continue
        if verdict is None:
            report.note(f"{label} is unsigned, so it is self reported")
        else:
            fingerprint = hair.fitting_signing.key_fingerprint(entry.get("key", ""))
            report.ok(f"{label} is signed and verifies (key {fingerprint})")

        complete.append(entry)
        bundles.append(bundle)

    if legacy:
        report.note(
            f"{_fittings(len(legacy))} ({', '.join(sorted(set(legacy)))}) "
            f"use the pre-claims shape. They bind a whole-file hash and say "
            f"nothing about which rows anybody walked, so they cannot be "
            f"counted under the claims model and are ignored here. Re-attest "
            f"in the closet on HAIR 0.9.5 or later to bring them back."
        )

    # Pooled coverage, across every bundle including the incomplete ones. It
    # answers a different question from the account count and both are worth
    # printing: coverage can reach the full row count while nobody at all has
    # proven the whole wig, and three people who each proved a different
    # third have not, between them, produced one person who can vouch for it.
    if digests:
        covered = hair.covered(bundles, digests)
        report.facts["coverage"] = {
            "covered": len(covered), "total": len(digests)
        }
        if len(covered) < len(digests):
            unproven = [
                signal.alias for signal in wig.signals
                if hair.signal_row_digest(signal) not in covered
            ]
            report.note(
                f"{len(covered)} of {len(digests)} rows proven by anybody. "
                f"Unclaimed: {', '.join(unproven[:6])}"
                + (" ..." if len(unproven) > 6 else "")
            )

    if not complete:
        report.fail(
            "no complete fitting survived the checks. Complete means one "
            "person claimed every row worked, bound to this wig_id, with a "
            "signature that verifies."
        )
        return

    report.facts["fittings"] = [
        {
            "handle": e.get("handle"),
            "github": e.get("github"),
            "date": e.get("date"),
            "rows": len(e.get("rows") or []),
            "key_fingerprint": hair.fitting_signing.key_fingerprint(
                e.get("key", "")
            ),
        }
        for e in complete
    ]

    # Distinct CONTRIBUTORS, not distinct strings, and only from fittings that
    # name a GitHub account. A display handle is what somebody typed as a name;
    # a GitHub handle is a claim a reviewer can go and check. The gate's whole
    # premise is three checkable people, so the two must not share a namespace.
    accounts: dict[str, list[str]] = {}
    unattributed = 0
    for entry in complete:
        account = github_key(entry.get("github"))
        if account is None:
            unattributed += 1
            continue
        display = str(entry.get("github") or entry.get("handle") or "?")
        accounts.setdefault(account, []).append(display)

    report.facts["accounts"] = sorted(accounts)
    report.facts["independent_accounts"] = len(accounts)
    report.ok(
        f"{len(complete)} complete fitting(s) from {len(accounts)} distinct "
        f"GitHub account(s): {', '.join(sorted(accounts)) or 'none'}"
    )

    for account, spellings in accounts.items():
        if len(set(spellings)) > 1:
            report.note(
                f"{len(spellings)} fittings spell one account "
                f"({account}) as {', '.join(sorted(set(spellings)))}. Counted "
                f"once."
            )
        elif len(spellings) > 1:
            report.note(
                f"{len(spellings)} fittings from {account}. Counted once."
            )

    if unattributed:
        report.note(
            f"{unattributed} complete fitting(s) carry no GitHub handle. They "
            f"prove the wig works and do not count toward the account total, "
            f"which counts checkable accounts."
        )

    # THE COUNT IS A REPORT, NOT A GATE (owner ruling 2026-08-04, following
    # HAIR's "there is no promotion bar", ruled 2026-08-02).
    #
    # The formal three-accounts rule is retired. It was machinery in a place
    # that should hold judgment: eligibility is a decision somebody makes
    # while looking at accumulated claims, and a rule that can be waived by
    # editing a file beside it was never really a rule. The Wig Shop reaching
    # the same conclusion is what makes this safe rather than lax: its shelf
    # now admits perfect fits only, so every wig arriving here already has at
    # least one person who claimed every row on their own hardware. The
    # question left is how MANY, and that is the owner's to weigh.
    #
    # So the gate reports and never refuses on this. --require-handles still
    # works for anybody who wants a hard floor on a particular run.
    if require_handles is not None and len(accounts) < require_handles:
        report.fail(
            f"{len(accounts)} distinct GitHub account(s), {require_handles} "
            f"required on this run."
        )
    elif len(accounts) < WIDELY_PROVEN_ACCOUNTS:
        report.note(
            f"{len(accounts)} of {WIDELY_PROVEN_ACCOUNTS} independent account(s). "
            f"Not a bar: every wig on the shelf is already a perfect fit, so "
            f"this is how widely proven it is, and whether that is enough is "
            f"the owner's call at publish time."
        )

    # A shared signing key means one install, which is a different claim from
    # one person. Grouped by canonical account so it reports in the same terms
    # as the count above.
    key_prints: dict[str, set[str]] = {}
    for entry in complete:
        fingerprint = hair.fitting_signing.key_fingerprint(entry.get("key", ""))
        if fingerprint:
            who = github_key(entry.get("github")) or str(
                entry.get("handle") or "?"
            )
            key_prints.setdefault(fingerprint, set()).add(who)
    for fingerprint, owners in key_prints.items():
        if len(owners) > 1:
            report.note(
                f"accounts {', '.join(sorted(owners))} share signing key "
                f"{fingerprint}, so they came from one install. Not a failure, "
                f"but they are one contributor when the accounts are counted."
            )


def _check_recipe(hair: Hair, wig: Any, report: Report) -> None:
    """Read the transmit recipe the wig states, and sanity check it.

    THIS IS NOT THE OLD SEND-TIMES AGGREGATE, and the difference matters.
    Before hair-wig/3, each fitter reported ``send_times_used``: how many
    presses THEIR room needed. The factory took the maximum across fitters,
    because a threshold is not a tendency and averaging [1, 3, 3] down to 2
    satisfies nobody who measured. From hair-wig/3 the wig itself states the
    recipe per row and a claim binds it by digest, so there is no longer a
    spread to aggregate: what the file says IS the answer, and disagreement
    between fitters shows up as one of them not claiming the row.

    What is left to do here is read it, clamp it, and say out loud when it
    asks for something a single knob in a generated integration cannot
    express.
    """
    recipes = wig_recipes(wig)
    if not recipes:
        # A matrix wig carries send counts on cells, not signals. The lattice
        # checks own that; nothing here applies.
        report.facts["recipe"] = {"rows": 0, "derived": None}
        return

    sends = sorted({r.send_count for r in recipes.values()})
    dittos = {a: r for a, r in recipes.items() if r.ditto_count}
    bypass = {a: r for a, r in recipes.items() if r.bypass_protocol}
    derived = max(sends)

    report.facts["recipe"] = {
        "rows": len(recipes),
        "derived": derived,
        "send_counts": sends,
        "dittos": {a: r.ditto_count for a, r in dittos.items()},
        "bypass": sorted(bypass),
        "uniform": len(sends) == 1 and not dittos and not bypass,
    }

    spread = f"{sends[0]}" if len(sends) == 1 else f"{sends[0]} to {sends[-1]}"
    report.ok(
        f"transmit recipe: {len(recipes)} row(s), send count {spread}, "
        f"{len(dittos)} with dittos, {len(bypass)} raw"
    )

    if len(sends) > 1:
        loud = sorted(
            (a for a, r in recipes.items() if r.send_count == derived)
        )
        report.note(
            f"the wig asks for different send counts per row ({spread}). A "
            f"single DEFAULT_SEND_COUNT cannot express that, so the "
            f"integration has to ship the highest, {derived}, and rows that "
            f"only wanted {sends[0]} will transmit more than they need. "
            f"Wanting {derived}: {', '.join(loud[:6])}"
            + (" ..." if len(loud) > 6 else "")
        )

    # Stated as a fact, not as an accusation. Whether the integration honours
    # these is check_recipe_conformance's business, and it runs later and
    # knows the answer; warning about a dropped ditto here would fire on every
    # run including the ones where nothing was dropped.
    if dittos:
        counts = sorted({r.ditto_count for r in dittos.values()})
        shape = str(counts[0]) if len(counts) == 1 else f"{counts[0]}-{counts[-1]}"
        listing = ", ".join(
            f"{alias} x{r.ditto_count}" for alias, r in sorted(dittos.items())
        )
        report.note(
            f"{len(dittos)} of {len(recipes)} row(s) ask for repeat frames "
            f"inside one transmission (ditto {shape}): {listing[:180]}"
            + ("..." if len(listing) > 180 else "")
        )

    if bypass:
        report.note(
            f"{len(bypass)} row(s) ask to bypass the encoder and send the raw "
            f"blob: {', '.join(sorted(bypass))}. A generated codebook re-encodes "
            f"from a decoded identity by construction, so these rows cannot go "
            f"through it."
        )

    # HAIR's comb calls this pair mutually exclusive and it is right: a raw
    # blob has no ditto grammar, because only the encoder renders a shortened
    # repeat frame. Whole-blob repetition is send_count's job. HAIR's own
    # exporter cannot produce this; a hand-edited file can.
    both = sorted(set(dittos) & set(bypass))
    if both:
        report.fail(
            f"{len(both)} row(s) set both bypass_protocol and a ditto count: "
            f"{', '.join(both)}. Only the encoder can render a repeat frame, "
            f"so a bypassed row asking for dittos describes a waveform "
            f"nothing can produce. Fix it in the wig."
        )


# ---------------------------------------------------------------------------
# The comb receipt
# ---------------------------------------------------------------------------


def _all_codes(hair: Hair, wig: Any) -> list[tuple[str, str]]:
    """Every transmittable code in the wig, as (row key, pronto)."""
    codes = [(signal.alias, signal.pronto) for signal in wig.signals]
    matrix = getattr(wig, "climate", None)
    if matrix is not None:
        for name in ("off", "on"):
            pronto = getattr(matrix, name, None)
            if pronto:
                codes.append((name, pronto))
        codes += [(hair.cell_key(cell), cell.pronto) for cell in matrix.cells]
        for extra in getattr(matrix, "extras", None) or []:
            codes += [
                (f"({extra.key}) {hair.cell_key(cell)}", cell.pronto)
                for cell in extra.cells
            ]
    return codes


def _check_carrierless(hair: Hair, wig: Any, report: Report) -> None:
    """Refuse codes that must go out with no carrier at all.

    HAIR 0.16.0 accepts a learned Pronto whose header is ``0100``: it states a
    time base where an ordinary code states a carrier frequency, and it has to
    be transmitted unmodulated. HAIR only offers such a code to an emitter that
    can send without a carrier. Whether an integration built on Home
    Assistant's ``infrared`` platform can do that has not been established, so
    the factory refuses rather than ship a code that would go out modulated
    and look like it worked.
    """
    bare = [
        key for key, pronto in _all_codes(hair, wig)
        if str(pronto).split()[:1] == ["0100"]
    ]
    if not bare:
        return
    shown = ", ".join(bare[:6])
    if len(bare) > 6:
        shown += f"; and {len(bare) - 6} more"
    report.fail(
        f"{len(bare)} code(s) carry no carrier (Pronto header 0100) and must be "
        f"sent unmodulated: {shown}. It is not yet established that a "
        f"generated integration can send one that way, so nothing is built "
        f"from this wig until it is."
    )


def _check_extras(matrix: Any, report: Report) -> None:
    """Refuse hair-wig/4 extra lattices until the gate checks them.

    A v4 wig carries peer lattices beside the main one, one per preset. They
    are real transmit recipes inside the signed cells hash, but every lattice
    check in this file walks ``matrix.cells`` only, so an extras lattice would
    pass without any of them having looked. Silence reads as approval, so
    this refuses instead.
    """
    extras = list(getattr(matrix, "extras", None) or [])
    if not extras:
        return
    report.facts["extras"] = [
        {"axis": e.axis, "key": e.key, "cells": len(e.cells)} for e in extras
    ]
    names = ", ".join(f"{e.axis} {e.key!r} ({len(e.cells)} cells)" for e in extras)
    report.fail(
        f"this matrix carries {len(extras)} extra lattice(s) (hair-wig/4): "
        f"{names}. The gate's lattice checks read the main lattice only, so "
        f"these codes would pass unchecked. Refused until the gate checks "
        f"every lattice a wig carries."
    )


def check_repairs(hair: Hair, wig: Any, live: Any | None, report: Report) -> None:
    """Say what the file CLAIMS was mended, and hold the claim to the codes.

    HAIR 0.14.0 writes a ``hair_repair`` record onto each code a person fixed
    on a device. It rides in the code's own extras, outside every canonical
    hash, so **nothing signs it**: it can be stamped onto any wig or stripped
    off one and every other check still passes. This reads it exactly as it
    reads a comb receipt, as the file's word about itself, and never as
    evidence. Refuses nothing on tier; a lattice already carries hundreds of
    codes nobody pressed, which is what a dimension checklist is.

    What it can check without trusting anybody: a code the file says was
    mended should no longer be one the live comb flags.
    """
    records: list[tuple[str, dict[str, Any]]] = []
    for signal in wig.signals:
        record = (getattr(signal, "extra", None) or {}).get(REPAIR_KEY)
        if isinstance(record, dict):
            records.append((signal.alias, record))
    matrix = getattr(wig, "climate", None)
    if matrix is not None:
        for cell in matrix.cells:
            record = (getattr(cell, "extra", None) or {}).get(REPAIR_KEY)
            if isinstance(record, dict):
                records.append((hair.cell_key(cell), record))
    if not records:
        return

    tiers: dict[str, int] = {}
    overridden: list[str] = []
    for key, record in records:
        tier = record.get("tier")
        tier = tier if tier in REPAIR_TIERS else "unstated"
        tiers[tier] = tiers.get(tier, 0) + 1
        if record.get("reading_disagreed"):
            overridden.append(key)
    report.facts["repairs"] = {
        "records": len(records),
        "tiers": {t: tiers[t] for t in (*REPAIR_TIERS, "unstated") if t in tiers},
        "overridden": overridden,
    }
    spread = ", ".join(
        f"{n} {t}" for t, n in report.facts["repairs"]["tiers"].items()
    )
    report.note(
        f"this file states that {len(records)} code(s) were repaired in HAIR "
        f"({spread}). Repair records sit outside every hash, so nothing signs "
        f"them: they are the file's word, not proof. air-tested means the fix "
        f"was fired at the device; rule-derived means it was written under a "
        f"field-map rule whose sample was fired; accepted means nothing was "
        f"transmitted."
    )
    if tiers.get("unstated"):
        report.note(
            f"{tiers['unstated']} repair record(s) state no tier, so they do not "
            f"even say whether anything was transmitted. HAIR writes a tier on "
            f"every repair it makes, so these came from somewhere else."
        )
    if overridden:
        shown = ", ".join(overridden[:6])
        report.note(
            f"{len(overridden)} repair(s) were kept after HAIR read the new "
            f"bytes as something other than their label: {shown}. That is how "
            f"a field map learns it is wrong, and worth reading."
        )
    if live is not None:
        claimed = {key for key, _record in records}
        still = sorted({
            key for finding in live.findings for key in finding.keys
            if key in claimed
        })
        if still:
            report.note(
                f"{len(still)} code(s) carry a repair record and are still "
                f"flagged by the live comb: {', '.join(still[:6])}. Whatever "
                f"the record says was done, those codes did not change."
            )


def check_comb(hair: Hair, wig: Any, report: Report) -> Any | None:
    """Comb the wig live with the pinned HAIR, and read the receipt as history.

    Three layers, each labelled for what it is:

    1. **The live comb.** HAIR's own current opinion of these bytes, run here
       and now. It cannot be forged and it cannot be out of date.
    2. **The stored receipt.** What whoever combed saw, when, with which HAIR.
       Provenance only. The Dreo fan's receipt says no suspects; a live comb
       flags Oscillate Horizontal, because the check that finds it shipped
       after the wig was combed. A receipt describes the HAIR that wrote it.
    3. **The gate's own checks** elsewhere in this file (lattice consistency,
       frame shape). The independent second opinion.

    The output worth reading is wherever those disagree. The live comb
    reports, with one exception: on a matrix, a wrong-state finding nobody
    has answered refuses (owner ruling 2026-09-23). See _refuse_wrong_state.

    Returns the live comb report, or None when the comb could not run.
    """
    live = _comb_live(hair, wig, report)
    receipt = _read_receipt(wig, report)
    if live is not None:
        _compare_receipt(live, receipt, report)
        _compare_with_ours(live, report)
        _attestations(hair, wig, live, receipt, report)
        _refuse_wrong_state(wig, live, report)
    return live


def _comb_live(hair: Hair, wig: Any, report: Report) -> Any | None:
    try:
        live = hair.comb(wig)
    except Exception as err:  # noqa: BLE001 - reported, and it is a refusal
        report.fail(
            f"HAIR {hair.version}'s comb could not run on this wig ({err!r}), "
            f"so nobody has checked its codes against each other here."
        )
        return None

    counts = dict(live.counts())
    unknown = sorted(set(counts) - COMB_CLASSES)
    coverage = live.coverage.to_dict() if live.coverage is not None else {}
    protocol = coverage.get("protocol") or {}
    report.facts["comb"] = {
        "live": {
            "hair": hair.version,
            "suspects": live.suspects,
            "counts": counts,
            "codes": coverage.get("codes"),
            "checked": coverage.get("checked"),
            "field_map": protocol.get("id"),
            "readable": protocol.get("readable"),
        },
    }
    if unknown:
        report.note(
            f"the comb reported class(es) this gate has no name for: "
            f"{', '.join(unknown)}. HAIR has grown a check; teach COMB_CLASSES."
        )

    suspects = [f for f in live.findings if not f.advisory]
    advisories = [f for f in live.findings if f.advisory]
    if not suspects:
        report.ok(f"combed live with HAIR {hair.version}: no suspects")
    else:
        detail = "; ".join(f"{k}: {v}" for k, v in counts.items())
        examples = []
        for finding in suspects[:6]:
            examples.append(f"{finding.check} on {' / '.join(finding.keys[:2])}")
        more = f"; and {len(suspects) - 6} more" if len(suspects) > 6 else ""
        report.note(
            f"combed live with HAIR {hair.version}: {live.suspects} suspect(s) "
            f"({detail}). {'; '.join(examples)}{more}."
        )
        wrong = [f for f in suspects if f.check in COMB_WRONG_STATE]
        # On a matrix these refuse, and _refuse_wrong_state names them.
        if wrong and getattr(wig, "climate", None) is None:
            keys = sorted({k for f in wrong for k in f.keys})
            report.note(
                f"{len(keys)} of those are codes that send a state other than "
                f"the one they are labelled with: {', '.join(keys[:6])}"
                + (f"; and {len(keys) - 6} more" if len(keys) > 6 else "")
                + ". That is the class that looks like it worked while landing "
                "on the wrong state."
            )
    if advisories:
        report.note(
            f"the comb also raised {len(advisories)} advisory finding(s) "
            f"({', '.join(sorted({f.check for f in advisories}))}), which are "
            f"worth a look and are never counted as suspects."
        )

    # What the comb could actually read. A lattice no field map covers passes
    # every structural check with not one byte of its payload read, and that
    # has to be said, because "no suspects" sounds the same either way.
    total = coverage.get("codes")
    if getattr(wig, "climate", None) is not None:
        if protocol.get("id"):
            report.ok(
                f"field map {protocol['id']} read {protocol.get('readable')} of "
                f"{protocol.get('codes', total)} code(s), so their contents were "
                f"checked against their labels, not only their shape"
            )
        else:
            report.note(
                f"no field map covers this protocol: 0 of {total} code(s) had "
                f"their contents checked. The comb compared their shapes only."
            )
    elif protocol.get("id"):
        report.ok(
            f"field map {protocol['id']} read {protocol.get('readable')} of "
            f"{protocol.get('codes', total)} code(s), so their checksums were "
            f"verified too"
        )
    return live


def _refuse_wrong_state(wig: Any, live: Any, report: Report) -> None:
    """Refuse a matrix whose cells the live comb says land on the wrong state.

    A wrong-state finding (``field-mismatch``, ``duplicated-neighbour``) on a
    climate cell means the code sent for one label sets the unit to another.
    A generated climate entity would then report the state it asked for
    while the unit sits in a different one, and nothing downstream can tell.
    The gate already refuses its own lattice defects of that kind, and HAIR
    will not open a Perfect Fit while such a finding is open, so an
    unanswered one refuses here too (owner ruling 2026-09-23).

    Answered means what it means in HAIR's Detangle: a person's attestation
    for that cell that still matches its current bytes and field-map version.
    Answers are tracked per cell, as HAIR tracks them, so one answered cell
    never answers its neighbour. Command wigs are unchanged: a flat command
    either works or visibly does not, and the fitting covers that.
    """
    if getattr(wig, "climate", None) is None:
        return
    by_key: dict[str, set[str]] = {}
    for finding in live.findings:
        if finding.advisory or finding.check not in COMB_WRONG_STATE:
            continue
        for key in finding.keys:
            by_key.setdefault(key, set()).add(finding.check)
    if not by_key:
        return
    comb = report.facts.setdefault("comb", {})
    standing = set((comb.get("attested") or {}).get("standing") or [])
    unanswered = sorted(k for k in by_key if k not in standing)
    answered = sorted(k for k in by_key if k in standing)
    comb["wrong_state"] = {"unanswered": unanswered, "answered": answered}
    if answered:
        report.note(
            f"{len(answered)} cell(s) the live comb says land on the wrong "
            f"state carry a standing answer from a person, so they do not "
            f"refuse: {', '.join(answered[:6])}"
            + (f"; and {len(answered) - 6} more" if len(answered) > 6 else "")
            + ". The answer is unsigned and the comb still doubts them."
        )
    if unanswered:
        shown = ", ".join(
            f"{key} ({', '.join(sorted(by_key[key]))})" for key in unanswered[:6]
        )
        more = f"; and {len(unanswered) - 6} more" if len(unanswered) > 6 else ""
        report.fail(
            f"the live comb says {len(unanswered)} cell(s) send a state other "
            f"than the one on their label, and nobody has answered it: "
            f"{shown}{more}. A climate entity built from this would report "
            f"one state while the unit sits in another. Repair or answer them "
            f"in HAIR's Needs attention, then save the wig again."
        )


def _read_receipt(wig: Any, report: Report) -> dict[str, Any] | None:
    comb = wig.extra.get("comb")
    if comb is None:
        report.note(
            "no stored comb receipt. Whoever made this wig never combed it, "
            "which is why the gate combs it itself."
        )
        return None
    if not isinstance(comb, dict) or not isinstance(comb.get("suspects"), int):
        report.note("the stored comb receipt is unreadable, so it says nothing")
        return None
    counts = comb.get("counts") if isinstance(comb.get("counts"), dict) else {}
    report.facts.setdefault("comb", {})["receipt"] = {
        "date": comb.get("date"),
        "version": comb.get("version"),
        "suspects": comb["suspects"],
        "counts": dict(counts),
    }
    return comb


def _compare_receipt(live: Any, receipt: dict[str, Any] | None, report: Report) -> None:
    """Hold the receipt a file carries against what the comb says today."""
    if receipt is None:
        return
    stored = receipt["suspects"]
    when = f" of {receipt['date']}" if receipt.get("date") else ""
    version = receipt.get("version")
    label = f"the stored receipt{when} (version {version})"
    stored_counts = receipt.get("counts")
    if not isinstance(stored_counts, dict):
        stored_counts = {}
    live_counts = dict(live.counts())
    if stored == live.suspects and stored_counts == live_counts:
        report.ok(f"{label} agrees with the live comb")
        return
    newer = sorted(set(live_counts) - set(stored_counts))
    gone = sorted(set(stored_counts) - set(live_counts))
    if live.suspects > stored:
        report.note(
            f"{label} records {stored} suspect(s); the live comb finds "
            f"{live.suspects}"
            + (f", in class(es) the receipt never mentions: {', '.join(newer)}"
               if newer else "")
            + ". A receipt describes the HAIR that wrote it, and newer HAIR "
            "checks more."
        )
    elif live.suspects < stored:
        report.facts["comb"]["repaired"] = stored - live.suspects
        report.ok(
            f"{label} records {stored} suspect(s) and the live comb finds "
            f"{live.suspects}"
            + (f"; gone entirely: {', '.join(gone)}" if gone else "")
            + ". That is what a completed repair looks like."
        )
    else:
        report.note(
            f"{label} and the live comb both count {stored} suspect(s) but "
            f"split them differently ({stored_counts} then, {live_counts} "
            f"now). Read both."
        )


def _compare_with_ours(live: Any, report: Report) -> None:
    """Where the gate's own independent checks and HAIR's comb disagree.

    Only on matrix wigs, where the gate reproduces some of the same classes
    itself. Compared per class, never as totals: a class one side cannot see
    must not cancel out a class it can.
    """
    if report.facts.get("shape") != "matrix":
        return
    shape = report.facts.get("frame_shape") or {}
    ours = {
        COMB_DUPLICATED_NEIGHBOUR: len(report.facts.get("lattice_defects") or []),
        COMB_MALFORMED: len(shape.get("malformed") or []),
        COMB_STRAY_BURST: len(shape.get("noisy") or []),
        COMB_MISSING_CELL: len(report.facts.get("missing_cells") or []),
    }
    theirs = dict(live.counts())
    for check, count in ours.items():
        if (count > 0) != (theirs.get(check, 0) > 0):
            report.note(
                f"the gate's own check and HAIR's comb disagree on {check}: "
                f"the gate counts {count}, the comb {theirs.get(check, 0)}. Two "
                f"implementations answering one question differently is worth "
                f"reading before anything is built."
            )


def _attestations(
    hair: Hair,
    wig: Any,
    live: Any,
    receipt: dict[str, Any] | None,
    report: Report,
) -> None:
    """A person's answers to findings, as the receipt records them.

    HAIR 0.14.0 lets somebody answer a finding without changing bytes ("use it
    anyway", "keep both"). The answer is keyed to the bytes and to the field
    map version, so it expires by itself when either changes. It is not signed
    by anything; the gate reports whether it still matches, never whether it
    was right.
    """
    records = (receipt or {}).get("attested")
    if not isinstance(records, list) or not records:
        return
    current: dict[str, set[str]] = {}
    for signal in wig.signals:
        current.setdefault(signal.alias, set()).update({
            hair.signal_row_digest(signal),
            hair.row_digest(signal.pronto, 0, False),
        })
    matrix = getattr(wig, "climate", None)
    if matrix is not None:
        for cell in matrix.cells:
            current.setdefault(hair.cell_key(cell), set()).add(
                hair.row_digest(cell.pronto, 0, False)
            )
    map_id = (report.facts.get("comb", {}).get("live") or {}).get("field_map")
    map_version = hair.field_map_version(map_id)

    standing, expired = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        target = record.get("target")
        stamped = (record.get("map") or {}).get("version")
        bytes_match = record.get("digest") in current.get(target, set())
        map_match = stamped is None or map_version is None or stamped == map_version
        (standing if bytes_match and map_match else expired).append(str(target))
    report.facts["comb"]["attested"] = {"standing": standing, "expired": expired}
    flagged = {k for f in live.findings for k in f.keys}
    answered = sorted(set(standing) & flagged)
    if standing:
        report.note(
            f"{len(standing)} finding(s) carry a person's answer in the receipt "
            f"that still matches the current bytes"
            + (f", including live findings on {', '.join(answered[:6])}"
               if answered else "")
            + ". The comb still doubts those codes and a person vouched for "
            "them; both are true, and neither is signed."
        )
    if expired:
        report.note(
            f"{len(expired)} answer(s) in the receipt no longer match: the bytes "
            f"or the field map changed since, so those findings are open again: "
            f"{', '.join(expired[:6])}."
        )


# ---------------------------------------------------------------------------
# Matrix wigs: checking a lattice instead of a codebook
# ---------------------------------------------------------------------------


def _axes(cell: Any) -> tuple[Any, Any, Any]:
    """The non-temperature coordinates of a cell: its row in the lattice."""
    return (
        getattr(cell, "mode", None),
        getattr(cell, "fan", None),
        getattr(cell, "swing", None),
    )


def check_matrix(hair: Hair, wig: Any, matrix: Any, report: Report) -> None:
    """Everything a state lattice has to be before anything is generated.

    A signal wig is checked by building a second implementation and making the
    two agree. A lattice has no codebook to disagree with, so the checks are
    about the lattice itself: is it complete, is it reachable, and does it
    contradict itself. Those turn out to catch real defects. Across six real
    SmartIR conversions they found four duplicate-neighbour temperatures, one
    truncated frame and one missing cell, none of which is visible to a human
    reading the file.
    """
    cells = list(matrix.cells)
    if not cells:
        report.fail("climate block has no cells")
        return

    report.facts["cell_count"] = len(cells)
    report.facts["modes"] = list(matrix.modes)
    report.facts["fan_modes"] = list(matrix.fan_modes)
    report.facts["swing_modes"] = list(matrix.swing_modes)
    report.facts["temp_range"] = [matrix.min_temp, matrix.max_temp]
    report.facts["precision"] = matrix.precision
    report.facts["has_on_code"] = matrix.on is not None

    # The unit is defaulted rather than written in every file seen so far, and
    # a Fahrenheit lattice read as Celsius is a silent 30-degree error. Assert
    # rather than assume: the day an F wig arrives it should stop the build.
    unit = getattr(matrix, "unit", "C")
    report.facts["unit"] = unit
    if unit != "C":
        report.fail(
            f"climate block is in {unit}, and every path here assumes Celsius. "
            f"Fahrenheit is a format feature nothing has exercised yet, so it "
            f"stops the build rather than being guessed at."
        )

    _check_lattice_shape(hair, matrix, cells, report)
    _check_lattice_consistency(hair, matrix, cells, report)


def _check_lattice_shape(
    hair: Hair, matrix: Any, cells: list[Any], report: Report
) -> None:
    """Completeness and reachability.

    Home Assistant's climate entity offers the user every combination of the
    modes, fan modes and swing modes the integration advertises. A hole in the
    lattice is therefore not a missing row in a table, it is a control that
    does nothing when somebody uses it, with no error and no log line.
    """
    temps = sorted({c.temp for c in cells if c.temp is not None})
    report.facts["temp_values"] = temps

    have = {(_axes(c), c.temp) for c in cells}
    missing: list[str] = []
    for mode in matrix.modes:
        for fan in matrix.fan_modes or [None]:
            for swing in matrix.swing_modes or [None]:
                for temp in temps or [None]:
                    if ((mode, fan, swing), temp) not in have:
                        missing.append(
                            "/".join(
                                str(p)
                                for p in (mode, fan, swing, temp)
                                if p is not None
                            )
                        )

    duplicates = collections.Counter((_axes(c), c.temp) for c in cells)
    repeated = [k for k, n in duplicates.items() if n > 1]
    if repeated:
        report.fail(
            f"{len(repeated)} coordinate(s) appear more than once in the "
            f"lattice. One state, one cell."
        )

    if missing:
        report.facts["missing_cells"] = missing
        shown = ", ".join(missing[:6])
        more = f", and {len(missing) - 6} more" if len(missing) > 6 else ""
        report.fail(
            f"{len(missing)} lattice cell(s) are missing: {shown}{more}. Home "
            f"Assistant will offer the user every combination the integration "
            f"advertises, so a hole is a control that silently does nothing."
        )
    else:
        report.ok(
            f"lattice complete: {len(cells)} cell(s) cover every combination "
            f"of {len(matrix.modes)} mode(s), "
            f"{len(matrix.fan_modes) or 1} fan setting(s), "
            f"{len(matrix.swing_modes) or 1} swing setting(s) and "
            f"{len(temps)} temperature(s)"
        )


def _check_lattice_consistency(
    hair: Hair, matrix: Any, cells: list[Any], report: Report
) -> None:
    """Does the lattice contradict itself?

    Duplicate codes inside a lattice are usually correct. A device that ignores
    temperature in fan_only genuinely sends one code for all of them, and that
    is a fact the generated integration needs, because offering a temperature
    control there would be a lie.

    The distinction that matters is whether the collapse is total. A whole row
    sharing one code means the device ignores that dimension. Part of a row
    sharing one code means the row proves the device responds to temperature,
    and then two values collide anyway. That is a defect, and on real files it
    is invariably a neighbour: 18 carrying 19's frame.
    """
    rows: dict[tuple[Any, Any, Any], dict[Any, str]] = {}
    for cell in cells:
        norm = " ".join(cell.pronto.split()).lower()
        rows.setdefault(_axes(cell), {})[cell.temp] = norm

    collapsed: list[tuple[Any, Any, Any]] = []
    defects: list[str] = []
    for axes, by_temp in rows.items():
        distinct = len(set(by_temp.values()))
        if len(by_temp) > 1 and distinct == 1:
            collapsed.append(axes)
        elif distinct != len(by_temp):
            inverse: dict[str, list[Any]] = {}
            for temp, pronto in by_temp.items():
                inverse.setdefault(pronto, []).append(temp)
            for clash in (v for v in inverse.values() if len(v) > 1):
                label = "/".join(str(p) for p in axes if p is not None)
                defects.append(f"{label} at {', '.join(str(t) for t in sorted(clash))}")

    report.facts["temperature_ignored_rows"] = [
        "/".join(str(p) for p in axes if p is not None) for axes in collapsed
    ]

    if collapsed:
        modes = sorted({str(a[0]) for a in collapsed})
        report.ok(
            f"{len(collapsed)} of {len(rows)} row(s) send one code for every "
            f"temperature, in mode(s) {', '.join(modes)}. The device ignores "
            f"temperature there and the integration must not offer it"
        )

    if defects:
        report.facts["lattice_defects"] = defects
        listing = "; ".join(defects[:8])
        more = f"; and {len(defects) - 8} more" if len(defects) > 8 else ""
        report.fail(
            f"{len(defects)} row(s) collide on some temperatures but not "
            f"others: {listing}{more}. The row proves the device responds to "
            f"temperature, so identical codes at two settings means one of "
            f"them transmits the wrong state. Fix the wig; do not generate "
            f"around it."
        )
    elif rows:
        report.ok(
            "no partial collisions: every row either varies with temperature "
            "throughout or ignores it throughout"
        )

    _check_frame_shape(hair, cells, report)


def _frame_shape(hair: Hair, pronto: str) -> tuple[int, ...] | None:
    """Timings per frame, splitting on any gap over 5ms.

    Every cell of one device sends the same protocol, so every cell should
    have the same frame shape. Comparing shapes rather than total Pronto
    length is what turns "this cell is different" into a diagnosis.
    """
    timings = hair.timings_from_pronto(pronto)
    if timings is None:
        return None
    frames: list[int] = []
    count = 0
    for value in timings:
        if value < 0 and -value > 5000:
            if count:
                frames.append(count)
                count = 0
            continue
        count += 1
    if count:
        frames.append(count)
    return tuple(frames)


def _check_frame_shape(hair: Hair, cells: list[Any], report: Report) -> None:
    """Every cell of one device should carry the same frame structure.

    Two things show up here, and they are not equally serious. A frame that is
    short is a truncated capture: bits are missing and the code is wrong. A
    stray extra burst after the last frame is capture noise that a receiver
    will ignore. Both are reported, only the first refuses.
    """
    shapes = collections.Counter(
        shape
        for shape in (_frame_shape(hair, c.pronto) for c in cells)
        if shape is not None
    )
    if not shapes:
        return
    normal, count = shapes.most_common(1)[0]
    if len(shapes) == 1:
        report.ok(
            f"every cell carries the same frame shape: "
            f"{len(normal)} frame(s) of {', '.join(str(n) for n in normal)} "
            f"timings"
        )
        return

    short: list[str] = []
    noisy: list[str] = []
    for cell in cells:
        shape = _frame_shape(hair, cell.pronto)
        if shape is None or shape == normal:
            continue
        key = hair.cell_key(cell)
        body = shape[: len(normal)]
        if len(shape) > len(normal) and body == normal:
            extra = shape[len(normal) :]
            noisy.append(f"{key} (+{sum(extra)} stray timing(s))")
        else:
            deltas = [
                b - a
                for a, b in zip(
                    normal,
                    body + (0,) * (len(normal) - len(body)),
                    strict=True,
                )
            ]
            noted = ", ".join(
                f"frame {i} {d:+d}" for i, d in enumerate(deltas) if d
            )
            short.append(f"{key} ({noted or 'different shape'})")

    report.facts["frame_shape"] = {
        "normal": list(normal),
        "malformed": short,
        "noisy": noisy,
    }
    if noisy:
        report.note(
            f"{len(noisy)} cell(s) carry a stray burst after the last frame: "
            f"{', '.join(noisy[:5])}. A receiver ignores it, so this is "
            f"capture noise rather than a wrong code, but it means the "
            f"capture was not clean."
        )
    if short:
        report.fail(
            f"{len(short)} cell(s) have a malformed frame against the "
            f"{count} that agree: {', '.join(short[:6])}. Timings missing "
            f"from a frame means bits missing from the code, and the device "
            f"will not do what the cell says."
        )


# ---------------------------------------------------------------------------
# Decoding the wig
# ---------------------------------------------------------------------------


def decode_wig(hair: Hair, wig: Any, report: Report) -> dict[str, Any]:
    """Decode every signal. The independent truth the rest is checked against."""
    identities: dict[str, Any] = {}
    protocols: set[str] = set()
    addresses: set[int] = set()

    undecoded: list[str] = []
    uncovered: list[str] = []
    unverified: list[str] = []

    for signal in wig.signals:
        raw = hair.timings_from_pronto(signal.pronto)
        if raw is None:
            report.fail(f"signal '{signal.alias}': Pronto does not convert to timings")
            undecoded.append(signal.alias)
            continue
        identity = hair.identity(raw)
        if identity is None:
            report.fail(
                f"signal '{signal.alias}': does not decode to any known protocol. "
                f"There is nothing to generate a codec from."
            )
            undecoded.append(signal.alias)
            continue
        identities[signal.alias] = identity
        protocols.add(identity.protocol)
        addresses.add(identity.address)

        # DECODE TRUST (HAIR 0.14.2). A generated codebook rebuilds every code
        # from its decoded label, so the label has to account for the whole
        # capture or the integration transmits something nobody fitted. HAIR
        # itself stopped rebuilding from such labels after it shipped an AC
        # whose state codes did exactly that. A row pinned to raw is not
        # rebuilt, so it is not asked.
        if getattr(signal, "bypass_protocol", False):
            continue
        covered = hair.covers_capture(raw)
        if covered is False:
            uncovered.append(signal.alias)
            report.fail(
                f"signal '{signal.alias}': HAIR reads it as {identity.protocol}, "
                f"but that label does not account for the whole capture. A "
                f"codebook rebuilt from the label would transmit something "
                f"other than what was fitted."
            )
        elif covered is None:
            unverified.append(signal.alias)

    if unverified:
        report.note(
            f"for {len(unverified)} signal(s) HAIR cannot say whether the label "
            f"accounts for the whole capture ({', '.join(unverified[:6])}"
            + (f"; and {len(unverified) - 6} more" if len(unverified) > 6 else "")
            + "). That is HAIR's answer for a decoder whose frame accounting it "
            "does not verify, usually upstream's. Not a refusal; the forward "
            "and reverse checks still have to pass."
        )
    report.facts["decode_trust"] = {
        "uncovered": uncovered,
        "unverified": unverified,
    }

    # signal_count is already recorded by the input gate; only the decoded
    # tally is new here, and the two being different is the whole point.
    total = len(wig.signals)
    report.facts["decoded_count"] = len(identities)

    if len(protocols) > 1:
        report.fail(
            f"wig mixes protocols ({', '.join(sorted(protocols))}). One wig, "
            f"one codec: split it before generating."
        )
    elif protocols:
        protocol = next(iter(protocols))
        report.facts["protocol"] = protocol
        source = next(iter(identities.values())).source
        # COUNT AGAINST THE WIG, NOT AGAINST THE SURVIVORS. Signals that fail
        # to decode fall out of `identities`, so counting that dict said "all
        # 6 signal(s) decode as SYMPHONY12" about a seven-signal wig with an
        # undecodable row, three lines above the failure saying so. A reader
        # skimming for the word "all" would have believed the wig was clean.
        # Same defect as reporting a bundle's own rows as the coverage total.
        if undecoded:
            report.note(
                f"{len(identities)} of {total} signal(s) decode as {protocol} "
                f"(decoder source: {source}). {len(undecoded)} did not: "
                f"{', '.join(undecoded)}."
            )
        else:
            report.ok(
                f"all {total} signal(s) decode as {protocol} "
                f"(decoder source: {source})"
            )

    if len(addresses) > 1:
        report.fail(
            f"wig carries more than one device address "
            f"({', '.join(hex(a) for a in sorted(addresses))}). That is two "
            f"devices in one file."
        )
    elif addresses:
        address = next(iter(addresses))
        report.facts["address"] = f"0x{address:02X}"
        report.ok(f"one device address throughout: 0x{address:02X}")

    return identities


# ---------------------------------------------------------------------------
# Loading the generated integration
# ---------------------------------------------------------------------------


_PKG = "_wigfactory_generated"


def _load_module(path: Path, stem: str) -> Any:
    """Import a generated file, with a package around it.

    Generated files import each other relatively (``from .decoder import
    ...``), so a bare file load is not enough. A synthetic package rooted at
    the component directory is registered once, and the files are imported
    as submodules of it. Nothing about the generated code has to change to
    be verifiable.
    """
    package_dir = path.parent
    if _PKG not in sys.modules:
        package = types.ModuleType(_PKG)
        package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
        sys.modules[_PKG] = package
    return importlib.import_module(f"{_PKG}.{stem}")


def find_integration_files(root: Path) -> tuple[Path | None, Path | None]:
    """Locate codes.py and an optional vendored decoder.py under an integration."""
    candidates = sorted(root.glob("custom_components/*/codes.py"))
    if not candidates:
        candidates = sorted(root.glob("**/codes.py"))
    codes = candidates[0] if candidates else None
    decoder = None
    if codes is not None:
        sibling = codes.parent / "decoder.py"
        if sibling.is_file():
            decoder = sibling
    return codes, decoder


# ---------------------------------------------------------------------------
# Step 4: forward, reverse and coverage
# ---------------------------------------------------------------------------


def check_forward(
    hair: Hair, codes: Any, wig_identities: dict[str, Any], report: Report
) -> None:
    """Encode through the generated codebook, decode through HAIR."""
    aliases = getattr(codes, "WIG_ALIASES", None)
    if not isinstance(aliases, dict) or not aliases:
        report.fail(
            "codes.py has no WIG_ALIASES mapping. The gate needs the alias to "
            "code link to check anything, and it is the provenance record."
        )
        return

    address = getattr(codes, "ADDRESS", None)
    wig_address = report.facts.get("address")
    if address is None:
        report.fail("codes.py has no module level ADDRESS constant")
    elif wig_address is not None and f"0x{int(address):02X}" != wig_address:
        report.fail(
            f"codes.py ADDRESS is 0x{int(address):02X} but the wig decodes to "
            f"{report.facts['address']}"
        )

    protocol = getattr(codes, "PROTOCOL", None)
    if protocol is None:
        report.fail("codes.py has no module level PROTOCOL constant")
    elif "protocol" in report.facts and str(protocol) != report.facts["protocol"]:
        report.fail(
            f"codes.py PROTOCOL is {protocol!r} but the wig decodes as "
            f"{report.facts['protocol']!r}"
        )

    checked = 0
    for alias, member in aliases.items():
        expected = wig_identities.get(alias)
        if expected is None:
            continue  # coverage reports this
        try:
            command = member.to_command()
        except Exception as err:  # a generated encoder must never raise here
            report.fail(f"'{alias}': to_command() raised {err!r}")
            continue
        try:
            raw = command.get_raw_timings()
        except Exception as err:
            report.fail(f"'{alias}': get_raw_timings() raised {err!r}")
            continue

        actual = hair.identity(raw)
        if actual is None:
            report.fail(
                f"'{alias}': the generated encoder produced timings HAIR "
                f"cannot decode at all"
            )
            continue
        if actual.fingerprint != expected.fingerprint:
            report.fail(
                f"'{alias}': encoder produces {actual.fingerprint}, wig says "
                f"{expected.fingerprint}"
            )
            continue
        checked += 1

    if checked:
        report.ok(
            f"forward: {checked} generated code(s) encode and decode back to "
            f"the wig's identity"
        )


def check_reverse(
    hair: Hair,
    decoder_module: Any,
    wig: Any,
    wig_identities: dict[str, Any],
    report: Report,
) -> None:
    """Decode the wig's own Pronto through the vendored RX decoder."""
    command_cls = None
    for value in vars(decoder_module).values():
        if isinstance(value, type) and hasattr(value, "from_raw_timings"):
            command_cls = value
            break
    if command_cls is None:
        report.fail(
            "the vendored decoder exposes no class with from_raw_timings. "
            "Keep the upstream shape: a classmethod taking signed timings."
        )
        return

    checked = 0
    for signal in wig.signals:
        expected = wig_identities.get(signal.alias)
        if expected is None:
            continue
        raw = hair.timings_from_pronto(signal.pronto)
        if raw is None:
            continue
        try:
            decoded = command_cls.from_raw_timings(list(raw))
        except Exception as err:
            report.fail(
                f"'{signal.alias}': the vendored decoder raised {err!r}. A "
                f"decoder must return None on malformed input, never raise."
            )
            continue
        if decoded is None:
            report.fail(
                f"'{signal.alias}': the vendored decoder cannot read a signal "
                f"HAIR decodes as {expected.fingerprint}"
            )
            continue
        if int(getattr(decoded, "address", -1)) != int(expected.address):
            report.fail(
                f"'{signal.alias}': vendored decoder reads address "
                f"0x{int(decoded.address):02X}, HAIR reads "
                f"0x{int(expected.address):02X}"
            )
            continue
        if int(getattr(decoded, "command", -1)) != int(expected.command):
            report.fail(
                f"'{signal.alias}': vendored decoder reads command "
                f"0x{int(decoded.command):02X}, HAIR reads "
                f"0x{int(expected.command):02X}"
            )
            continue
        checked += 1

    if checked:
        report.ok(
            f"reverse: {checked} wig signal(s) decode through the vendored "
            f"decoder to the same identity HAIR reads"
        )


def check_coverage(codes: Any, wig: Any, report: Report) -> None:
    """A bijection between wig aliases and codebook entries."""
    aliases = getattr(codes, "WIG_ALIASES", None)
    if not isinstance(aliases, dict):
        return

    wig_aliases = [signal.alias for signal in wig.signals]
    missing = [a for a in wig_aliases if a not in aliases]
    extra = [a for a in aliases if a not in wig_aliases]

    if missing:
        report.fail(
            f"{len(missing)} wig signal(s) have no codebook entry: "
            f"{', '.join(missing)}"
        )
    if extra:
        report.fail(
            f"{len(extra)} codebook entr(ies) are not in the wig: "
            f"{', '.join(extra)}"
        )

    values = [int(v) for v in aliases.values()]
    if len(set(values)) != len(values):
        collided = sorted({hex(v) for v in values if values.count(v) > 1})
        report.fail(
            f"two aliases map to the same code value: {', '.join(collided)}"
        )

    enum_members: set[int] = set()
    for value in vars(codes).values():
        if isinstance(value, type) and issubclass(value, IntEnum):
            enum_members |= {int(m) for m in value}
    orphans = enum_members - set(values)
    if orphans:
        report.fail(
            f"the code enum has {len(orphans)} member(s) no wig signal "
            f"produced: {', '.join(sorted(hex(o) for o in orphans))}. Every "
            f"code has to come from a signal somebody proved."
        )

    if not missing and not extra:
        report.ok(
            f"coverage: {len(wig_aliases)} signal(s) map one to one onto "
            f"{len(aliases)} codebook entr(ies)"
        )


def check_send_count(component_dir: Path, report: Report) -> None:
    """The shipped default must not sit below what the wig asks for.

    This is the whole point of carrying the recipe through. A wig asking for 3
    is saying one frame did not reliably reach the device, and an integration
    that ships a default of 1 anyway reproduces the fault whoever fitted it
    already found: buttons that work sometimes, with no pattern, on hardware
    that is fine. Shipping under the stated count is a defect the gate can
    see, so it refuses rather than warning.

    Shipping above it is allowed and merely noted. More frames costs airtime,
    not correctness.
    """
    recipe = report.facts.get("recipe") or {}
    derived = recipe.get("derived")
    constants = read_default_send_count(component_dir)
    default = constants.get("DEFAULT_SEND_COUNT")

    if default is None:
        if derived and derived > SEND_COUNT_MIN:
            report.fail(
                f"the wig asks for {derived} sends per press, and the "
                f"integration has no DEFAULT_SEND_COUNT to set. It will "
                f"transmit once and drop presses on the hardware somebody "
                f"already tested it on."
            )
        else:
            report.note(
                "the integration has no DEFAULT_SEND_COUNT. Fine for a device "
                "that answers a single frame; add one the moment a wig says "
                "otherwise."
            )
        return

    report.facts["default_send_count"] = default

    low = constants.get("MIN_SEND_COUNT", SEND_COUNT_MIN)
    high = constants.get("MAX_SEND_COUNT", SEND_COUNT_MAX)
    if not low <= default <= high:
        report.fail(
            f"DEFAULT_SEND_COUNT is {default}, outside the integration's own "
            f"{low}..{high} bounds. The shipped default has to be a value the "
            f"config flow will accept."
        )
    if high > SEND_COUNT_MAX:
        report.note(
            f"the integration allows up to {high} sends where HAIR clamps a "
            f"send count to {SEND_COUNT_MAX}. Above that the airtime costs "
            f"more than the reliability buys."
        )

    if derived is None:
        report.note(
            f"DEFAULT_SEND_COUNT is {default} with nothing in the wig behind "
            f"it. Not a failure, but the generated README should say where the "
            f"number came from."
        )
        return

    if default < derived:
        report.fail(
            f"DEFAULT_SEND_COUNT is {default} but the wig asks for {derived}. "
            f"Ship at least what the wig states, or the first thing a user "
            f"finds is the fickleness the fitter already diagnosed."
        )
    elif default > derived:
        report.ok(
            f"DEFAULT_SEND_COUNT {default} is at or above the wig's {derived}"
        )
        report.note(
            f"DEFAULT_SEND_COUNT is {default} where the wig asks for "
            f"{derived}. More conservative than the file, which is allowed; it "
            f"costs airtime and nothing else."
        )
    else:
        report.ok(
            f"DEFAULT_SEND_COUNT {default} matches the wig's {derived}"
        )


def check_recipe_conformance(codes: Any, wig: Any, report: Report) -> None:
    """The integration must reproduce every row's recipe, or say it cannot.

    The codec checks above prove the generated encoder puts the RIGHT
    IDENTITY on the air. They cannot prove it puts the right WAVEFORM on the
    air, because identity is what survives decoding and the recipe is what
    happens either side of it. From hair-wig/3 the row digest binds
    ``ditto_count`` and ``bypass_protocol``, so a claim is a statement about
    the waveform, and an integration that silently drops either one ships
    something nobody attested however green the forward and reverse checks
    are.

    The convention, mirroring ``WIG_ALIASES``: a generated codebook exposes
    ``WIG_RECIPE``, mapping the wig's alias verbatim to
    ``(send_count, ditto_count, bypass_protocol)``. It is optional only while
    every row is plain -- send count alone, no dittos, no bypass -- because
    that is the case DEFAULT_SEND_COUNT already covers on its own. The moment
    one row asks for more, the map is mandatory and is checked value by value.

    REFUSING IS THE POINT. Until the generator can express a ditto, the
    honest outcome for a wig that needs one is a refusal naming the rows, not
    a published integration that quietly rounds the waveform off.
    """
    stated = wig_recipes(wig)
    if not stated:
        return
    demanding = {a: r for a, r in stated.items() if not r.plain}
    declared = getattr(codes, "WIG_RECIPE", None)

    if declared is None:
        if not demanding:
            report.note(
                "the codebook declares no WIG_RECIPE. Fine here: every row "
                "wants a plain send count, which DEFAULT_SEND_COUNT covers."
            )
            return
        listing = ", ".join(
            f"{alias} ({r.describe()})" for alias, r in sorted(demanding.items())
        )
        report.fail(
            f"{len(demanding)} row(s) ask for a waveform this integration "
            f"cannot express, and the codebook declares no WIG_RECIPE: "
            f"{listing}. The row digest a fitter signed covers the ditto "
            f"count and the bypass flag, so publishing without them ships a "
            f"different waveform under somebody else's attestation. Teach the "
            f"integration the recipe, or leave this wig unpublished."
        )
        return

    if not isinstance(declared, dict):
        report.fail(
            f"WIG_RECIPE is {type(declared).__name__}, expected a dict keyed "
            f"by the wig's aliases."
        )
        return

    missing = sorted(set(stated) - set(declared))
    extra = sorted(set(declared) - set(stated))
    if missing:
        report.fail(
            f"WIG_RECIPE is missing {len(missing)} of the wig's rows: "
            f"{', '.join(missing[:6])}"
            + (" ..." if len(missing) > 6 else "")
        )
    if extra:
        report.fail(
            f"WIG_RECIPE names {len(extra)} row(s) the wig does not have: "
            f"{', '.join(extra[:6])}"
            + (" ..." if len(extra) > 6 else "")
        )

    mismatched: list[str] = []
    for alias, want in sorted(stated.items()):
        got = declared.get(alias)
        if got is None:
            continue
        try:
            send, ditto, bypass = got
            same = (
                int(send) == want.send_count
                and int(ditto) == want.ditto_count
                and bool(bypass) is want.bypass_protocol
            )
        except (TypeError, ValueError):
            mismatched.append(f"{alias}: {got!r} is not a 3-tuple")
            continue
        if not same:
            mismatched.append(
                f"{alias}: integration says {tuple(got)}, wig says "
                f"({want.send_count}, {want.ditto_count}, "
                f"{want.bypass_protocol})"
            )
    if mismatched:
        report.fail(
            f"{len(mismatched)} row(s) where WIG_RECIPE disagrees with the "
            f"wig: {'; '.join(mismatched[:4])}"
            + (" ..." if len(mismatched) > 4 else "")
        )
    elif not missing and not extra:
        report.ok(
            f"recipe: all {len(stated)} row(s) declared, matching the wig "
            f"({len(demanding)} needing more than a plain send count)"
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_report(report: Report, wig_path: Path, integration: Path | None) -> None:
    print(f"wig:         {wig_path}")
    if integration is not None:
        print(f"integration: {integration}")
    print()
    for line in report.checks:
        print(f"  PASS  {line}")
    for line in report.notes:
        print(f"  NOTE  {line}")
    for line in report.failures:
        print(f"  FAIL  {line}")
    print()
    if report.passed:
        print("GATE PASSED")
        if report.facts.get("content_hash"):
            print()
            print("Record these in the generated README:")
            print(f"  wig id:        {report.facts.get('wig_id') or 'none'}")
            print(f"  content hash:  {report.facts['content_hash']}")
            print(f"  protocol:      {report.facts.get('protocol', '?')}")
            print(f"  address:       {report.facts.get('address', '?')}")
            print(f"  HAIR version:  {report.facts.get('hair_version', '?')}")
            print(
                f"  upstream:      infrared-protocols "
                f"{report.facts.get('infrared_protocols', '?')}"
            )
            if report.facts.get("shop_commit"):
                print(
                    f"  source:        "
                    f"WigShop@{str(report.facts['shop_commit'])[:7]} "
                    f"({report.facts.get('shop_date', '?')})"
                )
            print(
                f"  accounts:      "
                f"{report.facts.get('independent_accounts', 0)} independent"
            )
            if report.facts.get("supersedes"):
                chain = report.facts["supersedes"]
                print(
                    f"  supersedes:    {chain[0]}"
                    + (f" (+{len(chain) - 1} older)" if len(chain) > 1 else "")
                )
            comb = report.facts.get("comb") or {}
            live = comb.get("live")
            if live:
                mapped = (
                    f", field map {live['field_map']} read "
                    f"{live.get('readable')} of {live.get('codes')}"
                    if live.get("field_map") else ""
                )
                print(
                    f"  combed:        live with HAIR {live.get('hair')}, "
                    f"{live.get('suspects')} suspect(s){mapped}"
                )
            stored = comb.get("receipt")
            if stored:
                print(
                    f"  receipt:       {stored.get('date') or 'undated'}, "
                    f"{stored.get('suspects')} suspect(s) (the file's own word)"
                )
            repairs = report.facts.get("repairs")
            if repairs:
                spread = ", ".join(
                    f"{n} {t}" for t, n in repairs["tiers"].items()
                )
                print(
                    f"  repaired:      {repairs['records']} code(s) ({spread}), "
                    f"as the file states"
                )
            recipe = report.facts.get("recipe") or {}
            if recipe.get("derived"):
                counts = recipe.get("send_counts") or []
                spread = (
                    f"{counts[0]}" if len(counts) == 1
                    else f"{counts[0]} to {counts[-1]}, shipping the highest"
                )
                extras = []
                if recipe.get("dittos"):
                    extras.append(f"{len(recipe['dittos'])} with dittos")
                if recipe.get("bypass"):
                    extras.append(f"{len(recipe['bypass'])} raw")
                tail = f", {', '.join(extras)}" if extras else ""
                print(
                    f"  send count:    {recipe['derived']} "
                    f"(stated by the wig, {spread}{tail})"
                )
            else:
                print("  send count:    not stated by the wig")
            climate = report.facts.get("climate_integration") or {}
            if climate:
                print(
                    f"  lattice:       {climate.get('states_walked')} requests "
                    f"resolved as HAIR resolves them, "
                    f"{climate.get('cells_reached')} of {climate.get('cells')} "
                    f"cells reachable"
                )
            cov = report.facts.get("coverage") or {}
            if cov:
                print(
                    f"  rows proven:   {cov.get('covered')} of "
                    f"{cov.get('total')}, pooled across every fitter"
                )
            for fitting in report.facts.get("fittings", []):
                print(
                    f"  fitting:       {fitting.get('handle')} "
                    f"(github: {fitting.get('github') or 'none'}) "
                    f"{fitting.get('date')} "
                    f"{fitting.get('rows')} row(s) "
                    f"key {fitting.get('key_fingerprint') or 'unsigned'}"
                )
    else:
        print(f"GATE FAILED: {len(report.failures)} problem(s). Nothing publishes.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a wig, and the integration generated from it."
    )
    parser.add_argument(
        "--wig",
        required=True,
        help=(
            "a path to a .wig.json, or a Wig Shop slug such as "
            "sanmli-candles-th05 resolved from the shop clone"
        ),
    )
    parser.add_argument(
        "--integration",
        type=Path,
        help="path to the generated integration repository root",
    )
    parser.add_argument(
        "--gate-only",
        action="store_true",
        help="run the input gate and the wig decode, then stop",
    )
    parser.add_argument(
        "--hair",
        type=Path,
        default=DEFAULT_HAIR,
        help=f"path to a HAIR checkout (default: {DEFAULT_HAIR})",
    )
    parser.add_argument(
        "--shop",
        type=Path,
        default=DEFAULT_SHOP,
        help=f"path to a Wig Shop checkout (default: {DEFAULT_SHOP})",
    )
    parser.add_argument(
        "--require-handles",
        type=int,
        metavar="N",
        help=(
            "fail unless the wig carries complete fittings from N distinct "
            "GitHub accounts. Off by default: the count is reported on every "
            "run and whether it is enough is a publishing judgment"
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    args = parser.parse_args(argv)

    hair = Hair(args.hair.resolve())
    report = Report()

    wig_path, provenance = locate_wig(args.wig, args.shop.resolve(), report)
    if provenance is not None:
        report.facts["shop_commit"] = provenance["sha"]
        report.facts["shop_date"] = provenance["date"]

    # OUTSIDE the provenance branch. A wig named by path carries no shop
    # commit and must still be gated; nesting this cost the entire gate on
    # every non-shop wig, silently, which is the worst shape a bug can take
    # in a file whose job is refusing things.
    wig = None
    identities: dict[str, Any] = {}
    if wig_path is not None:
        wig = run_input_gate(hair, wig_path, report, args.require_handles)
        identities = decode_wig(hair, wig, report) if wig is not None else {}

    climate_component = (
        find_climate_component(args.integration)
        if args.integration is not None else None
    )
    if wig is not None and not args.gate_only:
        if args.integration is None:
            report.fail("no --integration given, so nothing was verified")
        elif climate_component is not None or getattr(wig, "climate", None):
            if climate_component is None:
                report.fail(
                    f"the wig is a climate lattice, and no lattice.json with a "
                    f"lattice.py was found under {args.integration}"
                )
            else:
                check_climate_integration(
                    hair, wig, wig_path, climate_component, _load_module, report
                )
                check_send_count(climate_component, report)
        else:
            codes_path, decoder_path = find_integration_files(args.integration)
            if codes_path is None:
                report.fail(f"no codes.py found under {args.integration}")
            else:
                try:
                    codes = _load_module(codes_path, codes_path.stem)
                except Exception as err:
                    report.fail(f"codes.py does not import: {err!r}")
                    codes = None
                if codes is not None:
                    check_forward(hair, codes, identities, report)
                    check_coverage(codes, wig, report)
                    check_recipe_conformance(codes, wig, report)
                check_send_count(codes_path.parent, report)
            if decoder_path is not None:
                try:
                    decoder = _load_module(decoder_path, decoder_path.stem)
                except Exception as err:
                    report.fail(f"decoder.py does not import: {err!r}")
                else:
                    check_reverse(hair, decoder, wig, identities, report)
            elif codes_path is not None:
                report.note(
                    "no vendored decoder.py, so the reverse direction was not "
                    "checked. Buttons only integrations are allowed; hearing "
                    "the physical remote is not verified."
                )

    if args.json:
        print(json.dumps({
            "passed": report.passed,
            "checks": report.checks,
            "notes": report.notes,
            "failures": report.failures,
            "facts": report.facts,
        }, indent=2))
    else:
        print_report(report, wig_path or Path(str(args.wig)), args.integration)

    return EXIT_PASSED if report.passed else EXIT_REFUSED


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception:  # noqa: BLE001 - reported, and exits distinctly
        # A crash is a factory bug, never a finding about the wig, and it has
        # to exit differently from a refusal or CI cannot tell them apart.
        import traceback

        traceback.print_exc()
        raise environment_exit(
            "the gate crashed before reaching a verdict. That is a bug in the "
            "factory, not a finding about the wig."
        ) from None
