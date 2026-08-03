#!/usr/bin/env python3
"""Create the repository for a generated integration, and push it.

This is the one place in the factory that acts on the world without handing
the commands over first. That is deliberate and it is scoped: the whole point
of a factory is that it runs over many devices, and pasting repository setup
per device is the bottleneck it exists to remove.

Everything else here is caution.

**The gate runs again, here, now.** Not "the gate passed earlier". A green run
from ten minutes ago proves nothing about the tree in front of you, so
publication is gated by construction rather than by whoever remembered.

**Dry run unless --publish.** A bad run leaves a public repository carrying
somebody's organization name, and unlike a bad commit you cannot quietly amend
it away.

**Create only.** An existing repository is a refusal, not an update. Once
published, an integration has its own life: somebody opens a pull request, it
gets merged, and the repository now holds commits the factory has never seen.
A publisher that re-pushed would destroy them silently and the author would
find out from a user.

**The credential is never handled here.** Where `gh` is present and
authenticated, every call goes through it and the secret stays in the
operating system's keychain. Where it is not, a token is read from the
environment. Nothing reads a credential from a file in a repository, nothing
prints one, and nothing writes where one lives.

    publish/publish_integration.py --wig SLUG --integration PATH
    publish/publish_integration.py --wig SLUG --integration PATH --publish
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    DEFAULT_HAIR,
    DEFAULT_SHOP,
    OWNER,
    REPO_ROOT,
    GitHub,
    Refusal,
    describe,
    manifest_of,
    provenance_lines,
    repo_name_for,
    run_the_gate,
)

def push_initial_commit(
    integration: Path, repo: str, message: str, *, dry_run: bool
) -> None:
    """One clean commit in a fresh repository, not a subtree of the factory.

    A published integration wants its own history. Nobody reading it later
    should have to page through the factory's development to find out when
    the codec changed.
    """
    if dry_run:
        return
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / repo
        shutil.copytree(
            integration,
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
        )
        for args in (
            ["init", "-q", "-b", "main"],
            ["add", "-A"],
            ["-c", "user.name=WigFactory", "-c", "user.email=noreply@localhost",
             "commit", "-q", "-m", message],
            ["remote", "add", "origin", f"https://github.com/{OWNER}/{repo}.git"],
            ["push", "-q", "-u", "origin", "main"],
        ):
            result = subprocess.run(  # noqa: S603
                ["git", "-C", str(staging), *args],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                raise Refusal(
                    f"git {args[0]} failed: {(result.stdout + result.stderr).strip()}"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish a generated integration.")
    parser.add_argument("--wig", required=True, help="shop slug or path")
    parser.add_argument("--integration", required=True, type=Path)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    parser.add_argument("--shop", type=Path, default=DEFAULT_SHOP)
    parser.add_argument("--exemption", type=Path, default=REPO_ROOT / "EXEMPTIONS.md")
    parser.add_argument("--repo", help="override the derived repository name")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="actually create and push. Without it nothing is touched",
    )
    args = parser.parse_args(argv)

    try:
        report = run_the_gate(args)
        facts = report.get("facts") or {}

        stem = Path(args.wig).name.removesuffix(".json").removesuffix(".wig")
        repo = args.repo or repo_name_for(args.wig)
        description, topics = describe(facts)
        manifest = manifest_of(args.integration)
        tag = f"v{manifest.get('version', '0.1.0')}"

        github = GitHub(dry_run=not args.publish)
        # A dry run should still tell you what it would do even when it cannot
        # reach GitHub, so an indeterminate answer only stops a real publish.
        try:
            taken = github.repo_exists(repo)
        except Refusal:
            if args.publish:
                raise
            taken = False
            print("NOTE  could not check whether the repository already "
                  "exists from here. A real publish would refuse rather than "
                  "guess.\n")
        if taken:
            raise Refusal(
                f"{OWNER}/{repo} already exists. This tool creates and never "
                f"updates: a published integration accrues commits the factory "
                f"has never seen, and re-pushing would destroy them. Send a "
                f"pull request instead."
            )

        print(f"repository   {OWNER}/{repo}   public")
        print(f"description  {description}")
        print(f"topics       {', '.join(topics)}")
        print(f"domain       {manifest.get('domain')}")
        print(f"release      {tag}, notes generated")
        print(f"source       {args.integration}")
        print(f"access       {github.how}")
        for line in provenance_lines(facts):
            print(f"             {line}")
        print()

        if not args.publish:
            print("DRY RUN. Nothing was created. Add --publish to do it.")
            return 0

        github.create_repo(repo, description, topics)
        push_initial_commit(
            args.integration,
            repo,
            f"{manifest.get('name', repo)}\n\n"
            f"Generated by WigFactory from {stem}.\n\n"
            + "\n".join(provenance_lines(facts)) + "\n",
            dry_run=False,
        )
        github.create_release(repo, tag)
        print(f"PUBLISHED  https://github.com/{OWNER}/{repo}")
        print()
        print("From here it is an ordinary repository with an ordinary pull "
              "request process. The factory does not reach back in.")
        return 0
    except Refusal as err:
        print(f"REFUSED: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
