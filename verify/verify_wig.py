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

There is one further check that is not about the codec at all. A fitting made
on HAIR 0.9.0 or later records how many times each signal had to be
transmitted before the device answered. That is a measurement of somebody's
room, and the generated integration's shipped default must not sit below it,
because a codec can be perfectly correct and still appear broken if the frames
never arrive.

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
import importlib.util
import json
import sys
import types
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HAIR = REPO_ROOT / "reference" / "HAIR"
DEFAULT_SHOP = REPO_ROOT / "reference" / "WigShop"

# The standing promotion bar: three complete fittings from three distinct
# GitHub accounts. Reported always; enforced only with --require-handles,
# because the candle POC carries a written exemption and an exemption that
# is applied silently is not an exemption.
PROMOTION_HANDLES = 3

# The bounds every reader clamps send times to, matching HAIR's
# const.MAX_SEND_COUNT. One frame is the floor because zero sends is not a
# measurement, and ten is the ceiling because past that the airtime costs more
# than the reliability buys.
SEND_TIMES_MIN = 1
SEND_TIMES_MAX = 10

# The field a HAIR 0.9.0 fitting carries: how many times each signal was
# transmitted per press while somebody proved this wig on real hardware.
SEND_TIMES_KEY = "send_times_used"


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


# ---------------------------------------------------------------------------
# Exemptions
# ---------------------------------------------------------------------------


@dataclass
class Exemption:
    """One written waiver of the promotion bar, for one wig."""

    slug: str
    reason: str
    ruled_by: str
    date: str
    retires: str

    def summary(self) -> str:
        who = f" by {self.ruled_by}" if self.ruled_by else ""
        when = f" on {self.date}" if self.date else ""
        return f"exemption for {self.slug}, ruled{who}{when}"


def _table_field(section: str, label: str) -> str:
    """Pull a value out of a two-column markdown table row."""
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].casefold() == label.casefold():
            return cells[1].strip()
    return ""


def _bold_paragraph(section: str, label: str) -> str:
    """Pull the paragraph introduced by a bold run-in heading."""
    marker = f"**{label}.**"
    index = section.find(marker)
    if index < 0:
        return ""
    rest = section[index + len(marker) :]
    paragraph = rest.split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def read_exemptions(path: Path) -> dict[str, Exemption]:
    """Parse ``EXEMPTIONS.md`` into one entry per wig slug.

    Deliberately forgiving about layout and deliberately strict about the
    slug. An exemption covers exactly the wig named in its heading and never
    generalizes, because the failure this whole mechanism guards against is a
    waiver quietly becoming a policy.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    found: dict[str, Exemption] = {}
    sections = text.split("\n## ")
    for section in sections[1:]:
        heading, _, body = section.partition("\n")
        slug = heading.strip().strip("`").strip()
        if not slug or " " in slug:
            continue
        found[slug.casefold()] = Exemption(
            slug=slug,
            reason=_bold_paragraph(body, "Reason"),
            ruled_by=_table_field(body, "Ruled by"),
            date=_table_field(body, "Date"),
            retires=_table_field(body, "Retires when"),
        )
    return found


def wig_slug(wig_path: Path) -> str:
    """The shop slug a wig file corresponds to."""
    return wig_path.name.removesuffix(".json").removesuffix(".wig")


# ---------------------------------------------------------------------------
# Send times
# ---------------------------------------------------------------------------


def _fittings(count: int) -> str:
    """Pluralize a fitting count. Gate output gets read by people."""
    return f"{count} fitting" if count == 1 else f"{count} fittings"


def read_send_times(entry: dict[str, Any]) -> int | None:
    """Read ``send_times_used`` off one raw fitting, clamped, or None.

    ABSENT IS NOT 1. A fitting without the field was made before HAIR 0.9.0,
    or by a tool that does not write it, and claims nothing about how many
    frames the device needed. An explicit ``1`` is a different statement: the
    fitter had the control in front of them and one send was enough. Coercing
    the first into the second would let a wig from 2026-07 silently vouch for a
    default nobody measured, which is the exact false confidence the field was
    added to remove.

    ``bool`` is an ``int`` subclass, so ``True`` would otherwise read as 1.
    That is garbage arriving in a numeric field, not a measurement, so it is
    refused rather than believed.

    Clamped on read because a signature makes a value tamper evident, not
    sane: a fitting can be perfectly signed and still carry 1000.

    Kept deliberately in step with ``_read_send_times`` in HAIR's
    ``wig_fitting.py``. Where that module is importable the factory calls
    HAIR's aggregate instead of this, and this becomes the fallback for a HAIR
    checkout older than 0.9.0.
    """
    value = entry.get(SEND_TIMES_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(SEND_TIMES_MIN, min(value, SEND_TIMES_MAX))


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
        p.name.removesuffix(".wig.json")
        for p in wigs_dir.glob("*/*.wig.json")
    )
    stem = slug.removesuffix(".wig.json").removesuffix(".json")
    matches = sorted(wigs_dir.glob(f"*/{stem}.wig.json"))
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
            raise SystemExit(
                f"HAIR not found at {hair_root}. Run ./setup.sh first, or "
                f"pass --hair with the path to a HAIR checkout."
            )

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
        # Optional, and deliberately so. `wig_fitting` is where HAIR 0.9.0 put
        # `fitting_send_times_max`, which its own docstring calls the single
        # aggregation point for send times: ADOPT DEVICE, the factory and the
        # shop index all call it so the rule cannot drift. The factory would
        # rather use HAIR's answer than hold a second opinion. A HAIR checkout
        # older than 0.9.0 simply does not have it, and an older module can
        # also pull in a dependency the shim does not provide, so a failure to
        # import is a fallback and never a refusal.
        self.wig_fitting: Any | None
        try:
            self.wig_fitting = importlib.import_module(
                "custom_components.hair.wig_fitting"
            )
        except BaseException:  # noqa: BLE001 - see comment above
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

    def timings_from_pronto(self, pronto: str) -> list[int] | None:
        """Convert Pronto hex to signed microsecond timings."""
        try:
            command = self.ir_command.ProntoCommand(pronto)
        except (ValueError, IndexError):
            return None
        raw = command.get_raw_timings()
        return raw or None

    def content_hash(self, wig: Any) -> str:
        """The wig's canonical hash: signals for v1, cells for a matrix."""
        return self.wig_format.wig_content_hash(wig)

    def fitting_rows(self, wig: Any) -> list[tuple[str, str, int]]:
        """What a fitting walks: aliases for v1, the checklist for a matrix."""
        return self.wig_fitting.fitting_rows(wig)

    def cell_key(self, cell: Any) -> str:
        """HAIR's cell key, `cool/auto/23` shaped. Never reimplement this."""
        return self.wig_format.cell_key(cell)

    def send_times_max(self, wig: Any) -> int | None:
        """HAIR's own send-times aggregate, or None if this HAIR predates it."""
        aggregate = getattr(self.wig_fitting, "fitting_send_times_max", None)
        if aggregate is None:
            return None
        try:
            return int(aggregate(wig))
        except BaseException:  # noqa: BLE001 - fall back rather than refuse
            return None


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
    exemption: Exemption | None = None,
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
    report.facts["shape"] = "matrix" if matrix is not None else "signals"

    aliases = [signal.alias for signal in wig.signals]
    if len(set(aliases)) != len(aliases):
        duplicates = sorted({a for a in aliases if aliases.count(a) > 1})
        report.fail(f"duplicate aliases in the wig: {', '.join(duplicates)}")

    if matrix is not None:
        check_matrix(hair, wig, matrix, report)

    check_comb(wig, report)

    _check_fittings(hair, wig, report, require_handles, exemption)
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


def _check_fittings(
    hair: Hair,
    wig: Any,
    report: Report,
    require_handles: int | None = None,
    exemption: Exemption | None = None,
) -> None:
    """Fittings must exist, be complete, bind to these codes, and verify."""
    fittings = wig.extra.get("fittings")
    if not isinstance(fittings, list) or not fittings:
        report.fail(
            "wig carries no fitting. A wig without a fitting is a spreadsheet, "
            "and this factory does not take spreadsheets."
        )
        return

    # One path for both wig shapes, via HAIR's own definitions. For a signal
    # wig the hash covers the signals and the rows are aliases; for a matrix
    # the hash covers the cells and the rows are the dimension checklist, a
    # deterministic 12 to 20 row walk rather than the whole lattice. Nobody
    # fits 960 cells; everybody can fit every dimension.
    expected_hash = hair.content_hash(wig)
    report.facts["content_hash"] = expected_hash

    rows = {key for key, _, _ in hair.fitting_rows(wig)}
    report.facts["fitting_row_count"] = len(rows)
    complete: list[dict[str, Any]] = []

    for index, entry in enumerate(fittings):
        label = f"fittings[{index}]"
        if not isinstance(entry, dict):
            report.fail(f"{label} is not an object")
            continue
        handle = entry.get("handle") or "(no handle)"
        label = f"fitting by {handle}"

        confirmed = set(entry.get("confirmed") or [])
        failed = list(entry.get("failed") or [])
        missing = sorted(rows - confirmed)
        if failed:
            report.note(f"{label} is incomplete: {len(failed)} signal(s) failed")
            continue
        if missing:
            report.note(
                f"{label} is incomplete: {len(missing)} signal(s) untested"
            )
            continue

        entry_hash = entry.get("content_hash")
        if entry_hash != expected_hash:
            report.fail(
                f"{label} binds to {entry_hash}, but these codes hash to "
                f"{expected_hash}. The codes moved after somebody proved them."
            )
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

    if not complete:
        report.fail(
            "no complete fitting survived the checks. Complete means every "
            "signal confirmed, none failed, hash matching, signature valid."
        )
        return

    report.facts["fittings"] = [
        {
            "handle": e.get("handle"),
            "github": e.get("github"),
            "date": e.get("date"),
            "hair_version": e.get("hair_version"),
            "key_fingerprint": hair.fitting_signing.key_fingerprint(
                e.get("key", "")
            ),
            "send_times_used": read_send_times(e),
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
    report.facts["promotion_handles"] = len(accounts)
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
            f"prove the wig works and do not count toward the promotion bar, "
            f"which counts checkable accounts."
        )

    shortfall = None
    if len(accounts) < PROMOTION_HANDLES:
        shortfall = (
            f"{len(accounts)} of {PROMOTION_HANDLES} distinct GitHub accounts. "
            f"Below the standing promotion bar."
        )
    elif require_handles is not None and len(accounts) < require_handles:
        shortfall = (
            f"{len(accounts)} distinct GitHub accounts, {require_handles} "
            f"required on this run."
        )

    if shortfall is None:
        pass
    elif require_handles is None:
        report.note(
            shortfall + " Not enforced on this run; pass --require-handles "
            f"{PROMOTION_HANDLES} to make it a gate."
        )
    elif exemption is not None:
        # The waiver is quoted into the output rather than merely honoured, so
        # the published build's own log says out loud that it went out under
        # one, and why. An exemption nobody can see in the artifact is the
        # thing this mechanism exists to prevent.
        report.facts["exemption"] = {
            "slug": exemption.slug,
            "ruled_by": exemption.ruled_by,
            "date": exemption.date,
            "retires": exemption.retires,
        }
        report.note(
            f"{shortfall} WAIVED by a written {exemption.summary()}. "
            f"Reason: {exemption.reason or 'none recorded'}"
        )
        if exemption.retires:
            report.note(f"that exemption retires when: {exemption.retires}")
    else:
        report.fail(shortfall)

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
                f"but treat them as one contributor for promotion."
            )

    _check_send_times(hair, wig, complete, report)


def _check_send_times(
    hair: Hair, wig: Any, complete: list[dict[str, Any]], report: Report
) -> None:
    """Aggregate the send-times evidence the fittings carry.

    Max, never mean. Send times is a threshold and not a tendency: a fitter
    reporting 3 is saying "fewer than three was unreliable here", so averaging
    [1, 3, 3] down to 2 produces a number that satisfies nobody who measured.

    The spread is always printed alongside, because the max on its own hides
    the interesting case. Three fittings that all say 1 and one that says 8 is
    not a device that needs 8 frames, it is one room with a weak blaster, and
    the person reading the gate output is the one who should decide that.
    """
    observed: list[tuple[str, int]] = []
    silent = 0
    for entry in complete:
        who = str(entry.get("handle") or entry.get("github") or "?")
        value = read_send_times(entry)
        if value is None:
            silent += 1
            if SEND_TIMES_KEY in entry:
                report.note(
                    f"fitting by {who} carries a "
                    f"{SEND_TIMES_KEY} of {entry.get(SEND_TIMES_KEY)!r}, which "
                    f"is not a whole number of sends. Ignored: a garbled field "
                    f"claims nothing, and absent is not 1."
                )
            continue
        raw = entry.get(SEND_TIMES_KEY)
        if isinstance(raw, int) and raw != value:
            report.note(
                f"fitting by {who} records {SEND_TIMES_KEY} of {raw}, clamped "
                f"to {value}. A signature makes a value unaltered, not sane."
            )
        observed.append((who, value))

    facts: dict[str, Any] = {
        "reporting": len(observed),
        "silent": silent,
        "values": [{"who": who, "value": value} for who, value in observed],
    }

    if not observed:
        facts["derived"] = None
        facts["source"] = "none"
        report.facts["send_times"] = facts
        report.note(
            f"no complete fitting records {SEND_TIMES_KEY}, so there is no "
            f"evidence behind any send count. Absent is not 1: these fittings "
            f"predate HAIR 0.9.0 rather than proving one frame was enough. Ask "
            f"the fitter how many sends the device needed, and say in the "
            f"generated README that the number came from them and not from a "
            f"fitting."
        )
        return

    values = [value for _, value in observed]
    local_max = max(values)
    facts["min"] = min(values)
    facts["max"] = local_max

    # Prefer HAIR's aggregate where this checkout has one. Two implementations
    # of one rule is how the rule drifts.
    hair_max = hair.send_times_max(wig)
    if hair_max is None:
        derived = local_max
        source = f"factory fallback (HAIR {hair.version} has no aggregate)"
    else:
        derived = hair_max
        source = "HAIR fitting_send_times_max"
        if hair_max != local_max:
            # HAIR counts every complete, hash-valid fitting whether or not it
            # is signed; the factory's list has already had signature failures
            # removed, and a signature failure is a hard refusal above. So the
            # two agreeing is the normal case and a disagreement is worth
            # saying out loud rather than quietly resolving.
            derived = max(hair_max, local_max)
            report.note(
                f"HAIR reads a send-times max of {hair_max} and the factory "
                f"reads {local_max} from the fittings it accepted. Using the "
                f"higher, {derived}."
            )

    facts["derived"] = derived
    facts["source"] = source
    report.facts["send_times"] = facts

    spread = (
        f"{facts['min']} to {facts['max']}"
        if facts["min"] != facts["max"]
        else f"{facts['max']} throughout"
    )
    quiet = f", {silent} recording nothing" if silent else ""
    report.ok(
        f"send times: proven threshold {derived}, from "
        f"{_fittings(len(observed))} reporting it, spread {spread}{quiet}"
    )

    # The wig's own per signal send_count is a different claim: a property of
    # the code, where send times is a property of the room. A single knob in a
    # generated integration cannot express a per code repeat, so if a wig ever
    # carries one, say so rather than folding it into the default.
    dittos = [
        (key, count) for key, _, count in hair.fitting_rows(wig) if count > 1
    ]
    if dittos:
        listing = ", ".join(f"{alias} x{count}" for alias, count in dittos)
        report.note(
            f"{len(dittos)} signal(s) carry a send_count above 1 in the wig "
            f"itself: {listing}. That is a property of the code, not of the "
            f"room, and one send-count setting cannot express it. Generate a "
            f"per code repeat for those, or say in the README that they are "
            f"sent once."
        )


# ---------------------------------------------------------------------------
# The comb receipt
# ---------------------------------------------------------------------------


def check_comb(wig: Any, report: Report) -> None:
    """Read what HAIR's comb found, and treat it as provenance not proof.

    HAIR 0.9.1 checks a wig's codes against each other on import and leaves a
    receipt. It answers a question a fitting cannot: a fitting attests the
    dimension checklist, which on a matrix wig is nine rows out of hundreds,
    so a cell sending its neighbour's code sits under a complete signed
    fitting and nothing in the paperwork disagrees.

    **The gate does not trust it.** The receipt is unsigned and sits outside
    the canonical hash, so anybody can paste a clean one onto a broken wig.
    Every check here runs regardless, which makes forging it pointless, which
    is the property worth having. What the receipt is good for is provenance:
    who checked these codes, when, and with what result.

    So this reports and never refuses. Where the factory and the comb
    disagree, the disagreement is the interesting part and gets said out loud
    rather than resolved.
    """
    comb = wig.extra.get("comb")
    if comb is None:
        report.note(
            "no comb receipt. Nobody has checked this wig's codes against "
            "each other, which is not the same as their being clean. HAIR "
            "0.9.1 and newer records one on import."
        )
        return
    if not isinstance(comb, dict):
        report.note("the comb receipt is not an object, so it says nothing")
        return

    suspects = comb.get("suspects")
    dated = comb.get("date")
    when = f" on {dated}" if dated else ""
    if not isinstance(suspects, int):
        report.note(f"the comb receipt{when} carries no readable suspect count")
        return

    counts = comb.get("counts") if isinstance(comb.get("counts"), dict) else {}
    report.facts["comb"] = {
        "date": dated,
        "version": comb.get("version"),
        "suspects": suspects,
        "counts": dict(counts),
    }

    # What this run found on its own, so the two can be compared rather than
    # one being taken on faith.
    ours = len(report.facts.get("lattice_defects") or []) + len(
        (report.facts.get("frame_shape") or {}).get("malformed") or []
    ) + len(report.facts.get("missing_cells") or [])

    if suspects == 0:
        report.ok(f"combed{when}, no suspects recorded")
        if ours:
            report.note(
                f"but this run found {ours} problem(s) the receipt does not "
                f"mention. Either the comb predates the current codes, or its "
                f"checks and these ones do not cover the same ground. The "
                f"receipt does not bind to a content hash, so it cannot say "
                f"which."
            )
        return

    detail = "; ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    report.note(
        f"the comb found {suspects} suspect(s){when}"
        + (f" ({detail})" if detail else "")
        + ". Read the receipt: combing sees things a fitting cannot, because "
        "a checklist samples dimensions rather than cells."
    )

    findings = comb.get("findings")
    neighbours = [
        f
        for f in (findings if isinstance(findings, list) else [])
        if isinstance(f, dict) and f.get("check") == "duplicated-neighbour"
    ]
    if neighbours:
        rows = [
            " and ".join(f["keys"]) if isinstance(f.get("keys"), list) else "?"
            for f in neighbours[:6]
        ]
        more = f"; and {len(neighbours) - 6} more" if len(neighbours) > 6 else ""
        report.note(
            f"{len(neighbours)} of those send a neighbour's code: "
            f"{'; '.join(rows)}{more}. That is the class that looks like it "
            f"worked while landing on the wrong state."
        )
    truncated = comb.get("truncated")
    if isinstance(truncated, int) and truncated > 0:
        report.note(
            f"the receipt lists its findings up to a cap and omits "
            f"{truncated} more. The counts describe the whole result."
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
                for a, b in zip(normal, body + (0,) * (len(normal) - len(body)))
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

    for signal in wig.signals:
        raw = hair.timings_from_pronto(signal.pronto)
        if raw is None:
            report.fail(f"signal '{signal.alias}': Pronto does not convert to timings")
            continue
        identity = hair.identity(raw)
        if identity is None:
            report.fail(
                f"signal '{signal.alias}': does not decode to any known protocol. "
                f"There is nothing to generate a codec from."
            )
            continue
        identities[signal.alias] = identity
        protocols.add(identity.protocol)
        addresses.add(identity.address)

    if len(protocols) > 1:
        report.fail(
            f"wig mixes protocols ({', '.join(sorted(protocols))}). One wig, "
            f"one codec: split it before generating."
        )
    elif protocols:
        protocol = next(iter(protocols))
        report.facts["protocol"] = protocol
        source = next(iter(identities.values())).source
        report.ok(
            f"all {len(identities)} signal(s) decode as {protocol} "
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
    """The shipped default must not sit below what a fitter proved it needs.

    This is the whole point of carrying send times through. A fitting that says
    3 is a report that one frame did not reliably reach the device, and an
    integration that ships a default of 1 anyway reproduces the fault the
    fitter already found: buttons that work sometimes, with no pattern, on
    hardware that is fine. Shipping under the proven threshold is a defect the
    gate can see, so it refuses rather than warning.

    Shipping above it is allowed and merely noted. More frames costs airtime,
    not correctness.
    """
    send_times = report.facts.get("send_times") or {}
    derived = send_times.get("derived")
    constants = read_default_send_count(component_dir)
    default = constants.get("DEFAULT_SEND_COUNT")

    if default is None:
        if derived and derived > SEND_TIMES_MIN:
            report.fail(
                f"the fittings prove this device needs {derived} sends per "
                f"press, and the integration has no DEFAULT_SEND_COUNT to set. "
                f"It will transmit once and drop presses on the hardware "
                f"somebody already tested it on."
            )
        else:
            report.note(
                "the integration has no DEFAULT_SEND_COUNT. Fine for a device "
                "that answers a single frame; add one the moment a fitting "
                "says otherwise."
            )
        return

    report.facts["default_send_count"] = default

    low = constants.get("MIN_SEND_COUNT", SEND_TIMES_MIN)
    high = constants.get("MAX_SEND_COUNT", SEND_TIMES_MAX)
    if not low <= default <= high:
        report.fail(
            f"DEFAULT_SEND_COUNT is {default}, outside the integration's own "
            f"{low}..{high} bounds. The shipped default has to be a value the "
            f"config flow will accept."
        )
    if high > SEND_TIMES_MAX:
        report.note(
            f"the integration allows up to {high} sends where HAIR clamps send "
            f"times to {SEND_TIMES_MAX}. Above that the airtime costs more than "
            f"the reliability buys."
        )

    if derived is None:
        report.note(
            f"DEFAULT_SEND_COUNT is {default} with no fitting evidence behind "
            f"it. Not a failure, but the generated README should say where the "
            f"number came from."
        )
        return

    if default < derived:
        report.fail(
            f"DEFAULT_SEND_COUNT is {default} but the fittings prove "
            f"{derived} sends were needed. Ship at least what somebody "
            f"measured, or the first thing a user finds is the fickleness the "
            f"fitter already diagnosed."
        )
    elif default > derived:
        report.ok(
            f"DEFAULT_SEND_COUNT {default} is at or above the proven threshold "
            f"of {derived}"
        )
        report.note(
            f"DEFAULT_SEND_COUNT is {default} where the fittings prove "
            f"{derived}. More conservative than the evidence, which is allowed; "
            f"it costs airtime and nothing else."
        )
    else:
        report.ok(
            f"DEFAULT_SEND_COUNT {default} matches the proven threshold of "
            f"{derived}"
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
            print(f"  content hash:  {report.facts['content_hash']}")
            print(f"  protocol:      {report.facts.get('protocol', '?')}")
            print(f"  address:       {report.facts.get('address', '?')}")
            print(f"  HAIR version:  {report.facts.get('hair_version', '?')}")
            if report.facts.get("shop_commit"):
                print(
                    f"  source:        WigShop@{report.facts['shop_commit']} "
                    f"({report.facts.get('shop_date', '?')})"
                )
            print(
                f"  accounts:      {report.facts.get('promotion_handles', 0)} "
                f"of {PROMOTION_HANDLES} for promotion"
            )
            comb = report.facts.get("comb")
            if comb:
                print(
                    f"  combed:        {comb.get('date') or 'undated'}, "
                    f"{comb.get('suspects')} suspect(s) "
                    f"(receipt, not independently verified)"
                )
            else:
                print("  combed:        no receipt")
            send_times = report.facts.get("send_times") or {}
            if send_times.get("derived"):
                basis = (
                    f"max across "
                    f"{_fittings(int(send_times.get('reporting') or 0))}, "
                    f"spread {send_times.get('min')} to "
                    f"{send_times.get('max')}"
                )
                print(f"  send times:    {send_times['derived']} ({basis})")
            else:
                print(
                    "  send times:    not recorded by any fitting. Ask the "
                    "fitter, and say so."
                )
            for fitting in report.facts.get("fittings", []):
                sends = fitting.get("send_times_used")
                print(
                    f"  fitting:       {fitting.get('handle')} "
                    f"(github: {fitting.get('github') or 'none'}) "
                    f"{fitting.get('date')} "
                    f"HAIR {fitting.get('hair_version')} "
                    f"key {fitting.get('key_fingerprint') or 'unsigned'} "
                    f"sends {sends if sends is not None else 'not recorded'}"
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
            "GitHub accounts. The standing promotion bar is "
            f"{PROMOTION_HANDLES}; leave it off only where a written "
            "exemption applies"
        ),
    )
    parser.add_argument(
        "--exemption",
        type=Path,
        metavar="FILE",
        help=(
            "a written waiver file, normally EXEMPTIONS.md. Used with "
            "--require-handles: an entry naming this wig turns the handle "
            "failure into a note that quotes the reason into the build "
            "output. No matching entry and the gate still refuses"
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

    exemption = None
    if args.exemption is not None and wig_path is not None:
        entries = read_exemptions(args.exemption)
        if not entries:
            report.note(
                f"no exemptions could be read from {args.exemption}. The bar "
                f"stands."
            )
        exemption = entries.get(wig_slug(wig_path).casefold())
        if exemption is None and entries:
            report.note(
                f"{args.exemption} carries no entry for "
                f"'{wig_slug(wig_path)}'. One wig's waiver never covers "
                f"another, so the bar stands."
            )

    wig = None
    identities: dict[str, Any] = {}
    if wig_path is not None:
        wig = run_input_gate(
            hair, wig_path, report, args.require_handles, exemption
        )
        identities = decode_wig(hair, wig, report) if wig is not None else {}

    if wig is not None and not args.gate_only:
        if args.integration is None:
            report.fail("no --integration given, so nothing was verified")
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

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
