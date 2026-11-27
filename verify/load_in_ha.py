#!/usr/bin/env python3
"""Load a built integration in a real Home Assistant, and say what it logged.

The gate proves an integration says what its wig says. It cannot prove that
the Home Assistant people actually run still loads it quietly, and that can
change with no change to the wig at all: 2026.11 renamed the climate
temperature members, and the published Daikin FTXS50KVM 0.1.0 logged seven
warnings on every install, each asking the user to report it, while every
check here and the published repository's own hassfest and HACS runs stayed
green. Neither of those loads the integration's Python.

This does. With Home Assistant installed in the running interpreter:

- every module in the integration imports;
- the entry sets up through the integration's own ``async_setup_entry``,
  and every platform it forwards adds its entities;
- each entity is added and driven the way a user would drive it: a climate
  entity turned on at a temperature, off, changed while off, and restored
  from what it saved; a button pressed; a light, fan or media player turned
  on and off; and after every step Home Assistant's own reads of its state;
- every action that should transmit does, into a recording emitter;
- nothing logs a warning or worse.

    python verify/load_in_ha.py --integration <device>/<repo>
    python verify/load_in_ha.py --integration <path> --report report.md
    python verify/load_in_ha.py --requirements <path>    # what to pip install
    python verify/load_in_ha.py --plan                   # the CI matrix

Exit 0 when it loads clean, 1 when it does not, 3 when there was no verdict
(Home Assistant is not installed here, or this script itself broke).

``--plan`` needs no Home Assistant. It reads every built integration's
``hacs.json`` and PyPI's release list and prints the legs the weekly
compatibility workflow runs: for each integration, the newest patch of the
minimum Home Assistant it declares, the newest stable release, and the newest
beta when one is ahead of stable.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import re
import sys
import tempfile
import traceback
import urllib.request
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPI = "https://pypi.org/pypi/homeassistant/json"

EMITTER = "infrared.compat_emitter"
RECEIVER = "infrared.compat_receiver"


# --- which integrations, and which Home Assistant ---------------------------


def built_integrations(root: Path = REPO_ROOT) -> list[Path]:
    """Every integration this repository has built, found by manifest."""
    found = []
    for manifest in sorted(root.glob("*/*/custom_components/*/manifest.json")):
        integration = manifest.parents[2]
        if integration.relative_to(root).parts[0] != "reference":
            found.append(integration)
    return found


_VERSION = re.compile(r"^(\d{4})\.(\d+)\.(\d+)(?:b(\d+))?$")


def _key(version: str) -> tuple[int, int, int, float] | None:
    match = _VERSION.match(version)
    if not match:
        return None
    year, month, patch, beta = match.groups()
    return (int(year), int(month), int(patch), float(beta) if beta else float("inf"))


def _minor(version: str) -> str:
    year, month = version.split(".")[:2]
    return f"{year}.{month}"


def plan(releases: dict[str, list[dict[str, Any]]], root: Path = REPO_ROOT) -> list:
    """The compatibility legs, one per integration and Home Assistant release."""
    usable = {
        v: _key(v)
        for v, files in releases.items()
        if _key(v) and files and not all(f.get("yanked") for f in files)
    }
    ordered = sorted(usable, key=usable.__getitem__)
    stable = [v for v in ordered if usable[v][3] == float("inf")]
    newest_stable = stable[-1]
    newest = ordered[-1]

    legs = []
    for integration in built_integrations(root):
        hacs = json.loads((integration / "hacs.json").read_text(encoding="utf-8"))
        floor_minor = _minor(str(hacs.get("homeassistant", newest_stable)))
        floor = [v for v in stable if _minor(v) == floor_minor]
        lines = {"floor": floor[-1] if floor else None, "stable": newest_stable}
        if newest != newest_stable:
            lines["beta"] = newest
        seen: set[str] = set()
        for line, version in lines.items():
            if version is None or version in seen:
                continue
            seen.add(version)
            legs.append(
                {
                    "repo": integration.name,
                    "path": str(integration.relative_to(root)),
                    "line": line,
                    "ha": version,
                    "minor": _minor(version),
                }
            )
    return legs


def print_plan() -> int:
    with urllib.request.urlopen(PYPI, timeout=60) as response:
        releases = json.load(response)["releases"]
    print(f"matrix={json.dumps(plan(releases))}")
    return 0


def requirements(integration: Path) -> list[str]:
    """What to install beside Home Assistant before loading ``integration``.

    The infrared library at exactly the version this Home Assistant pins in
    its own infrared component, since that is what a user's install runs, and
    whatever the integration's manifest asks for.
    """
    import homeassistant.components.infrared as infrared

    pinned = json.loads(
        (Path(infrared.__file__).parent / "manifest.json").read_text(encoding="utf-8")
    )["requirements"]
    (component,) = _component(integration)
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    return [*pinned, *manifest.get("requirements", [])]


# --- loading one integration -------------------------------------------------


def _component(integration: Path) -> list[Path]:
    return [
        p.parent for p in (integration / "custom_components").glob("*/manifest.json")
    ]


@dataclass
class Run:
    ha_version: str = "?"
    infrared_protocols: str = "?"
    checks: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    logged: list[str] = field(default_factory=list)
    # Python's own warnings raised inside Home Assistant or a library, about
    # code that is not the integration's. Counted and shown, never a failure:
    # nothing in the factory can act on them, and a red leg for Home
    # Assistant's quarrel with aiohttp would teach everybody to ignore red.
    elsewhere: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.problems and not self.logged


class _Capture(logging.Handler):
    """Every warning or worse, sorted into the integration's and not."""

    def __init__(self, run: Run, component: Path) -> None:
        super().__init__(logging.WARNING)
        self.run = run
        self.marks = (str(component), f"custom_components/{component.name}/")
        self.domain = component.name

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        line = f"{record.levelname} {record.name}: {message}"
        ours = (
            record.name != "py.warnings"
            or any(mark in message for mark in self.marks)
            or record.name.startswith(self.domain)
        )
        (self.run.logged if ours else self.run.elsewhere).append(line)


def _read_state(entity: Any) -> None:
    """What Home Assistant reads off an entity when it writes its state."""
    _ = entity.state
    _ = entity.capability_attributes
    _ = entity.state_attributes
    _ = entity.extra_state_attributes


async def _drive(entity: Any, run: Run, hass: Any) -> None:
    """Use the entity the way a user would, by what kind of entity it is."""
    from homeassistant.components.button import ButtonEntity
    from homeassistant.components.climate import ClimateEntity, HVACMode
    from homeassistant.components.event import EventEntity

    name = f"{type(entity).__name__} {entity.unique_id}"

    async def step(label: str, coro: Any, *, sends: bool = True) -> None:
        sent = len(entity.sent)
        await coro
        _read_state(entity)
        if sends and len(entity.sent) == sent:
            run.problems.append(f"{name}: {label} sent nothing")
        run.checks.append(f"{name}: {label}")

    if isinstance(entity, ClimateEntity):
        mode = next(m for m in entity.hvac_modes if m != HVACMode.OFF)
        middle = (entity.min_temp + entity.max_temp) / 2
        await step(
            f"on in {mode} at {middle:g}",
            entity.async_set_temperature(temperature=middle, hvac_mode=mode),
        )
        await step("off", entity.async_turn_off())
        await step(
            "a temperature change while off",
            entity.async_set_temperature(temperature=entity.max_temp),
            sends=False,
        )
        saved = entity.extra_restore_state_data
        if saved is not None:
            twin = await _twin(entity, saved, hass)
            if twin is not None:
                _read_state(twin)
                if twin.extra_restore_state_data.as_dict() != saved.as_dict():
                    run.problems.append(
                        f"{name}: restored {twin.extra_restore_state_data.as_dict()} "
                        f"from {saved.as_dict()}"
                    )
                else:
                    run.checks.append(f"{name}: restores what it saved")
    elif isinstance(entity, ButtonEntity):
        await step("pressed", entity.async_press())
    elif isinstance(entity, EventEntity):
        _read_state(entity)
        run.checks.append(f"{name}: read")
    elif hasattr(entity, "async_turn_on") and hasattr(entity, "async_turn_off"):
        await step("on", entity.async_turn_on())
        await step("off", entity.async_turn_off())
    else:
        _read_state(entity)
        run.checks.append(f"{name}: read")


_FACTORY: dict[int, Any] = {}


async def _twin(entity: Any, saved: Any, hass: Any) -> Any:
    """A fresh copy of ``entity``, added with ``saved`` as its last state."""
    make = _FACTORY.get(id(entity))
    if make is None:
        return None
    twin = await make()
    if twin is None:
        return None
    await _add(twin, hass, restore=saved)
    return twin


async def _add(entity: Any, hass: Any, restore: Any = None) -> None:
    """Attach ``entity`` to hass the way a platform would, minus the registry."""
    entity.hass = hass
    entity.entity_id = f"{_platform_of(entity)}.compat_{len(_FACTORY)}_{id(entity)}"
    entity.async_write_ha_state = lambda: _read_state(entity)
    entity.sent = []

    async def _send(command: Any) -> None:
        entity.sent.append(command)
        if hasattr(command, "get_raw_timings"):
            command.get_raw_timings()

    async def _last_extra() -> Any:
        return restore

    async def _last_state() -> None:
        return None

    entity._send_command = _send
    entity.async_get_last_extra_data = _last_extra
    entity.async_get_last_state = _last_state
    await entity.async_added_to_hass()


def _platform_of(entity: Any) -> str:
    module = type(entity).__module__.rsplit(".", 1)[-1]
    return module if module.isidentifier() else "entity"


async def _load(integration: Path, run: Run) -> None:
    from homeassistant import loader
    from homeassistant.const import __version__
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import frame
    from homeassistant.util.unit_system import METRIC_SYSTEM

    run.ha_version = __version__
    (component,) = _component(integration)
    domain = component.name

    with tempfile.TemporaryDirectory() as config_dir:
        hass = HomeAssistant(config_dir)
        hass.config.units = METRIC_SYSTEM
        loader.async_setup(hass)
        frame.async_setup(hass)

        sys.path.insert(0, str(component.parent))
        try:
            modules = {}
            for source in sorted(component.glob("*.py")):
                name = (
                    domain if source.stem == "__init__" else f"{domain}.{source.stem}"
                )
                modules[name] = importlib.import_module(name)
            run.checks.append(f"imports {len(modules)} module(s)")

            const = modules.get(f"{domain}.const")
            data = {}
            for attr, value in vars(const).items() if const else ():
                if attr.startswith("CONF_") and attr.endswith("ENTITY_ID"):
                    data[value] = RECEIVER if "RECEIVER" in attr else EMITTER
            entry = SimpleNamespace(
                entry_id="compat",
                title=domain,
                domain=domain,
                data=data,
                options={},
                runtime_data=None,
                async_on_unload=lambda _f: None,
                add_update_listener=lambda _f: lambda: None,
            )

            added: list[Any] = []

            async def forward(_entry: Any, platforms: Any) -> bool:
                for platform in platforms:
                    module = modules[f"{domain}.{platform}"]
                    before = len(added)

                    def collect(entities: Any, *_: Any, **__: Any) -> None:
                        added.extend(entities)

                    await module.async_setup_entry(hass, entry, collect)
                    for entity in added[before:]:
                        _FACTORY[id(entity)] = _remaker(module, entry, entity)
                return True

            hass.config_entries = SimpleNamespace(
                async_forward_entry_setups=forward,
                async_unload_platforms=lambda *_: asyncio.sleep(0, True),
            )
            if not await modules[domain].async_setup_entry(hass, entry):
                run.problems.append("async_setup_entry returned False")
                return
            run.checks.append(f"sets up {len(added)} entities")

            for entity in added:
                await _add(entity, hass)
                _read_state(entity)
                await _drive(entity, run, hass)
        finally:
            sys.path.remove(str(component.parent))
            await hass.async_stop(force=True)


def _remaker(module: Any, entry: Any, entity: Any) -> Any:
    """How to build another one of ``entity``: rerun its platform's setup."""

    async def make() -> Any:
        again: list[Any] = []
        await module.async_setup_entry(
            entity.hass, entry, lambda es, *_a, **_k: again.extend(es)
        )
        return next((e for e in again if e.unique_id == entity.unique_id), None)

    return make


def run_one(integration: Path) -> Run:
    run = Run()
    (component,) = _component(integration)
    capture = _Capture(run, component)
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.WARNING)
    logging.captureWarnings(True)
    warnings.simplefilter("default")
    try:
        import importlib.metadata as metadata

        run.infrared_protocols = metadata.version("infrared-protocols")
        asyncio.run(_load(integration, run))
    except Exception as err:  # noqa: BLE001 -- reported, with where
        frames = traceback.extract_tb(err.__traceback__)
        here = next(
            (f for f in reversed(frames) if "custom_components" in f.filename),
            frames[-1] if frames else None,
        )
        where = f" at {Path(here.filename).name}:{here.lineno}" if here else ""
        run.problems.append(f"{type(err).__name__}: {err}{where}")
    finally:
        root.removeHandler(capture)
    return run


def render(integration: Path, run: Run) -> str:
    """The run as Markdown, for a job summary or an issue body."""
    verdict = "loads clean" if run.clean else "does not load clean"
    lines = [
        f"`{integration.name}` {verdict} on Home Assistant {run.ha_version} "
        f"(infrared-protocols {run.infrared_protocols}).",
        "",
    ]
    if run.problems:
        lines += ["**Problems**", ""] + [f"- {p}" for p in run.problems] + [""]
    if run.logged:
        lines += ["**Logged**", ""] + [f"- `{w}`" for w in run.logged] + [""]
    lines += ["**Checked**", ""] + [f"- {c}" for c in run.checks]
    if run.elsewhere:
        lines += [
            "",
            f"{len(run.elsewhere)} Python warning(s) from Home Assistant or a "
            f"library about their own code, not counted:",
            "",
        ] + [f"- `{w.splitlines()[0]}`" for w in run.elsewhere]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--integration", type=Path)
    what.add_argument("--requirements", type=Path, metavar="INTEGRATION")
    what.add_argument("--plan", action="store_true")
    parser.add_argument("--report", type=Path, help="also write the run as Markdown")
    args = parser.parse_args(argv)

    if args.plan:
        return print_plan()
    try:
        import homeassistant  # noqa: F401, PLC0415
    except ImportError:
        print("Home Assistant is not installed here, so there is no verdict.")
        return 3
    if args.requirements:
        print("\n".join(requirements(args.requirements.resolve())))
        return 0

    integration = args.integration.resolve()
    run = run_one(integration)
    text = render(integration, run)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    return 0 if run.clean else 1


if __name__ == "__main__":
    sys.exit(main())
