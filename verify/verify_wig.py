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


def run_input_gate(hair: Hair, wig_path: Path, report: Report) -> Any | None:
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

    if getattr(wig, "climate", None) is not None:
        report.fail(
            "matrix wigs (hair-wig/2 climate block) are out of scope. A codec "
            "that compresses a state matrix is the next target, not this one."
        )
        return None

    if not wig.signals:
        report.fail("wig has no signals")
        return None

    report.facts["name"] = wig.name
    report.facts["brand"] = wig.brand
    report.facts["model"] = wig.model
    report.facts["kind"] = wig.kind
    report.facts["signal_count"] = len(wig.signals)
    report.facts["hair_version"] = hair.version

    aliases = [signal.alias for signal in wig.signals]
    if len(set(aliases)) != len(aliases):
        duplicates = sorted({a for a in aliases if aliases.count(a) > 1})
        report.fail(f"duplicate aliases in the wig: {', '.join(duplicates)}")

    _check_fittings(hair, wig, report)
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


def _check_fittings(hair: Hair, wig: Any, report: Report) -> None:
    """Fittings must exist, be complete, bind to these codes, and verify."""
    fittings = wig.extra.get("fittings")
    if not isinstance(fittings, list) or not fittings:
        report.fail(
            "wig carries no fitting. A wig without a fitting is a spreadsheet, "
            "and this factory does not take spreadsheets."
        )
        return

    expected_hash = hair.wig_format.signals_content_hash(wig.signals)
    report.facts["content_hash"] = expected_hash

    rows = {signal.alias for signal in wig.signals}
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

    handles = sorted({
        str(e.get("github") or e.get("handle") or "?") for e in complete
    })
    report.facts["fittings"] = [
        {
            "handle": e.get("handle"),
            "github": e.get("github"),
            "date": e.get("date"),
            "hair_version": e.get("hair_version"),
            "key_fingerprint": hair.fitting_signing.key_fingerprint(
                e.get("key", "")
            ),
        }
        for e in complete
    ]
    report.ok(
        f"{len(complete)} complete fitting(s) from {len(handles)} handle(s): "
        f"{', '.join(handles)}"
    )

    key_prints: dict[str, list[str]] = {}
    for entry in complete:
        fingerprint = hair.fitting_signing.key_fingerprint(entry.get("key", ""))
        if fingerprint:
            key_prints.setdefault(fingerprint, []).append(
                str(entry.get("github") or entry.get("handle") or "?")
            )
    for fingerprint, owners in key_prints.items():
        if len(set(owners)) > 1:
            report.note(
                f"handles {', '.join(sorted(set(owners)))} share signing key "
                f"{fingerprint}, so they came from one install. Not a failure, "
                f"but they do not count as distinct for promotion."
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
            for fitting in report.facts.get("fittings", []):
                print(
                    f"  fitting:       {fitting.get('handle')} "
                    f"(github: {fitting.get('github') or 'none'}) "
                    f"{fitting.get('date')} "
                    f"HAIR {fitting.get('hair_version')} "
                    f"key {fitting.get('key_fingerprint') or 'unsigned'}"
                )
    else:
        print(f"GATE FAILED: {len(report.failures)} problem(s). Nothing publishes.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a wig, and the integration generated from it."
    )
    parser.add_argument("--wig", required=True, type=Path, help="path to a .wig.json")
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
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    args = parser.parse_args(argv)

    hair = Hair(args.hair.resolve())
    report = Report()

    wig = run_input_gate(hair, args.wig, report)
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
        print_report(report, args.wig, args.integration)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
