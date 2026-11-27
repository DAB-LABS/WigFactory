#!/usr/bin/env python3
"""Which Home Assistant releases the weekly compatibility job loads.

``load_in_ha.py --plan`` turns every built integration's ``hacs.json`` and
PyPI's release list into the legs of ``integrations.yml``. Getting that
wrong fails quietly: a job that tests the wrong release is green for the
wrong reason. These scenarios run the planner on hand-written release lists:

- the floor is the newest patch of the minimum in hacs.json, not the minimum
- the newest stable release is always a leg
- a beta is a leg only while it is ahead of stable
- yanked releases and anything not shaped like a release are skipped
- a floor equal to the newest stable is one leg, not two

    .venv/bin/python verify/test_load_plan.py

Needs neither Home Assistant nor the network. Exit 0 means every scenario
behaved.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_in_ha import plan  # noqa: E402

FILE = [{"yanked": False}]


def releases(*versions: str, yanked: tuple[str, ...] = ()) -> dict:
    out = {v: list(FILE) for v in versions}
    for v in yanked:
        out[v] = [{"yanked": True}]
    return out


def legs(release_list: dict, floor: str) -> list[tuple[str, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        component = root / "dev" / "dev-ir" / "custom_components" / "dev_ir"
        component.mkdir(parents=True)
        (component / "manifest.json").write_text("{}", encoding="utf-8")
        (component.parents[1] / "hacs.json").write_text(
            json.dumps({"homeassistant": floor}), encoding="utf-8"
        )
        return [(leg["line"], leg["ha"]) for leg in plan(release_list, root)]


def floor_is_newest_patch() -> list[str]:
    got = legs(releases("2026.6.0", "2026.6.4", "2026.6.1", "2026.11.3"), "2026.6.0")
    want = [("floor", "2026.6.4"), ("stable", "2026.11.3")]
    return [] if got == want else [f"got {got}, want {want}"]


def beta_ahead_of_stable() -> list[str]:
    got = legs(
        releases("2026.6.4", "2026.11.3", "2026.12.0b1", "2026.12.0b2"), "2026.6.0"
    )
    want = [("floor", "2026.6.4"), ("stable", "2026.11.3"), ("beta", "2026.12.0b2")]
    return [] if got == want else [f"got {got}, want {want}"]


def beta_behind_stable_is_dropped() -> list[str]:
    got = legs(releases("2026.6.4", "2026.11.0b6", "2026.11.0"), "2026.6.0")
    want = [("floor", "2026.6.4"), ("stable", "2026.11.0")]
    return [] if got == want else [f"got {got}, want {want}"]


def yanked_and_odd_versions_skipped() -> list[str]:
    got = legs(
        releases("2026.6.4", "2026.11.3", "2026.11.4.dev0", yanked=("2026.11.5",)),
        "2026.6.0",
    )
    want = [("floor", "2026.6.4"), ("stable", "2026.11.3")]
    return [] if got == want else [f"got {got}, want {want}"]


def floor_equal_to_stable_is_one_leg() -> list[str]:
    got = legs(releases("2026.11.2", "2026.11.3"), "2026.11.0")
    want = [("floor", "2026.11.3")]
    return [] if got == want else [f"got {got}, want {want}"]


SCENARIOS: list[tuple[str, Callable[[], list[str]]]] = [
    ("the floor is the newest patch of the hacs.json minimum", floor_is_newest_patch),
    ("a beta ahead of stable is a leg", beta_ahead_of_stable),
    ("a beta behind stable is not", beta_behind_stable_is_dropped),
    ("yanked releases and dev builds are skipped", yanked_and_odd_versions_skipped),
    ("a floor that is the newest stable is one leg", floor_equal_to_stable_is_one_leg),
]


def main() -> int:
    print("compatibility legs from hacs.json and the release list\n")
    failures = 0
    for title, scenario in SCENARIOS:
        problems = scenario()
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
