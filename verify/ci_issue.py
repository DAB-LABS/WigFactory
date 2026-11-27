#!/usr/bin/env python3
"""Open, refresh or close the one issue that tracks a scheduled check.

A red X on a scheduled run notifies nobody. The weekly run against HAIR main
went red on 2026-11-16 and stayed that way, unread, for eleven days. So a
scheduled check that fails says so in an issue, which GitHub does notify
about, and the same issue closes itself when the check passes again.

One issue per title, and the title is the key: a check that keeps failing
refreshes the body of the issue it already has instead of opening another,
so a fortnight of failures is one issue, not two.

    python verify/ci_issue.py --title T --label L --failing --body-file F
    python verify/ci_issue.py --title T --label L --passing

Runs in GitHub Actions with GH_TOKEN set to the workflow's own token, which
needs ``issues: write``. Exit 0 when the issue now says what the check
found, 2 when it could not be updated. The workflow step that runs this
never decides the job's colour: the check it reports on already did.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

LABEL_COLOUR = "d93f0b"


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {result.stderr.strip()}")
    return result.stdout


def run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run}" if repo and run else "this run"


def open_issue(repo: str, title: str, label: str) -> int | None:
    found = json.loads(
        gh(
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            label,
            "--limit",
            "100",
            "--json",
            "number,title",
        )
    )
    return next((i["number"] for i in found if i["title"] == title), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--label-description", default="Opened by a scheduled check")
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--failing", action="store_true")
    state.add_argument("--passing", action="store_true")
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args(argv)

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("GITHUB_REPOSITORY is not set; this runs in GitHub Actions.")
        return 2
    try:
        number = open_issue(repo, args.title, args.label)
        if args.passing:
            if number is None:
                print(f"passing, and no open issue titled {args.title!r}")
                return 0
            gh(
                "issue",
                "close",
                str(number),
                "--repo",
                repo,
                "--comment",
                f"Passes again in {run_url()}.",
            )
            print(f"closed #{number}")
            return 0

        body = args.body_file.read_text(encoding="utf-8") if args.body_file else ""
        body = f"{body.rstrip()}\n\nLatest failing run: {run_url()}\n"
        body_path = Path(os.environ.get("RUNNER_TEMP", ".")) / "ci-issue-body.md"
        body_path.write_text(body, encoding="utf-8")
        if number is None:
            gh(
                "label",
                "create",
                args.label,
                "--repo",
                repo,
                "--force",
                "--color",
                LABEL_COLOUR,
                "--description",
                args.label_description,
            )
            url = gh(
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                args.title,
                "--label",
                args.label,
                "--body-file",
                str(body_path),
            ).strip()
            print(f"opened {url}")
        else:
            gh(
                "issue",
                "edit",
                str(number),
                "--repo",
                repo,
                "--body-file",
                str(body_path),
            )
            print(f"refreshed #{number}")
        return 0
    except RuntimeError as err:
        print(f"could not update the issue: {err}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
