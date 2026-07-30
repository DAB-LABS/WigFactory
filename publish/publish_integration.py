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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))

from verify_wig import (  # noqa: E402
    DEFAULT_HAIR,
    DEFAULT_SHOP,
    PROMOTION_HANDLES,
    REPO_ROOT,
)

OWNER = "DAB-LABS"

# The medium, and the reason the domain carries it too. RF is the obvious
# second one.
MEDIUM_SUFFIX = "-ir"

# GitHub lowercases topics itself and caps them at 35 characters. Kept short
# and descriptive; the two HACS-flavoured ones are conventional rather than
# required, since the action only checks that the list is not empty.
BASE_TOPICS = ("home-assistant", "hacs-integration", "infrared")

TOKEN_VARS = ("GITHUB_TOKEN", "GH_TOKEN")


class Refusal(Exception):
    """Something is not right, and nothing should be created."""


# ---------------------------------------------------------------------------
# Talking to GitHub without holding the secret
# ---------------------------------------------------------------------------


def _gh_available() -> bool:
    if shutil.which("gh") is None:
        return False
    result = subprocess.run(  # noqa: S603
        ["gh", "auth", "status"], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


class GitHub:
    """The smallest surface that creates a repository and cuts a release."""

    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.via_gh = _gh_available()
        self.token = next(
            (os.environ[v] for v in TOKEN_VARS if os.environ.get(v)), None
        )
        if not self.via_gh and not self.token:
            raise Refusal(
                "no GitHub access. Either authenticate the gh command line, "
                "which keeps the credential in the operating system keychain "
                "and out of this process entirely, or put a token in the "
                "environment."
            )

    @property
    def how(self) -> str:
        return "gh (credential in the keychain)" if self.via_gh else "environment token"

    def _run(self, args: list[str]) -> tuple[int, str]:
        result = subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, check=False
        )
        return result.returncode, (result.stdout + result.stderr).strip()

    def _api(self, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"https://api.github.com{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "wigfactory",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode()
        except OSError as err:
            return 0, str(err)

    def repo_exists(self, repo: str) -> bool:
        """True if it exists. Raises if the answer cannot be established.

        "I could not tell" must never read as "it is not there". A proxy, an
        expired token or a network blip would otherwise turn the create-only
        guarantee into a best effort, and the failure mode is pushing a fresh
        initial commit over a repository that has a life of its own.
        """
        if self.via_gh:
            code, out = self._run(["gh", "repo", "view", f"{OWNER}/{repo}"])
            if code == 0:
                return True
            if "Could not resolve" in out or "not found" in out.lower():
                return False
            raise Refusal(
                f"could not establish whether {OWNER}/{repo} exists: {out}"
            )
        status, out = self._api("GET", f"/repos/{OWNER}/{repo}")
        if status == 200:
            return True
        if status == 404:
            return False
        raise Refusal(
            f"could not establish whether {OWNER}/{repo} exists (HTTP "
            f"{status}). Refusing rather than assuming it is free."
        )

    def create_repo(self, repo: str, description: str, topics: list[str]) -> None:
        if self.dry_run:
            return
        if self.via_gh:
            code, out = self._run(
                [
                    "gh", "repo", "create", f"{OWNER}/{repo}",
                    "--public", "--description", description,
                ]
            )
            if code != 0:
                raise Refusal(f"could not create the repository: {out}")
            code, out = self._run(
                ["gh", "repo", "edit", f"{OWNER}/{repo}", "--enable-issues"]
                + [arg for t in topics for arg in ("--add-topic", t)]
            )
            if code != 0:
                raise Refusal(f"repository created, but settings failed: {out}")
            return
        # A personal account and an organization take different endpoints,
        # and guessing wrong is a 404 at the worst possible moment. Ask.
        status, body = self._api("GET", f"/users/{OWNER}")
        if status != 200:
            raise Refusal(f"could not look up {OWNER} ({status}): {body}")
        is_org = json.loads(body).get("type") == "Organization"
        status, out = self._api(
            "POST",
            f"/orgs/{OWNER}/repos" if is_org else "/user/repos",
            {
                "name": repo,
                "description": description,
                "private": False,
                "has_issues": True,
                "has_wiki": False,
                "has_projects": False,
            },
        )
        if status not in (200, 201):
            raise Refusal(f"could not create the repository ({status}): {out}")
        status, out = self._api(
            "PUT", f"/repos/{OWNER}/{repo}/topics", {"names": topics}
        )
        if status not in (200, 201):
            raise Refusal(f"repository created, but topics failed: {out}")

    def create_release(self, repo: str, tag: str) -> None:
        if self.dry_run:
            return
        if self.via_gh:
            code, out = self._run(
                [
                    "gh", "release", "create", tag,
                    "--repo", f"{OWNER}/{repo}",
                    "--title", tag,
                    "--generate-notes",
                ]
            )
            if code != 0:
                raise Refusal(f"could not cut the release: {out}")
            return
        status, out = self._api(
            "POST",
            f"/repos/{OWNER}/{repo}/releases",
            {"tag_name": tag, "name": tag, "generate_release_notes": True},
        )
        if status not in (200, 201):
            raise Refusal(f"could not cut the release ({status}): {out}")


# ---------------------------------------------------------------------------
# What to publish, derived from the wig rather than invented
# ---------------------------------------------------------------------------


def topic_safe(value: str) -> str | None:
    """GitHub's rules: lowercase, alphanumeric and hyphens, 35 characters."""
    slug = re.sub(r"[^a-z0-9-]+", "-", str(value).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:35].strip("-")
    return slug or None


def describe(facts: dict[str, Any]) -> tuple[str, list[str]]:
    """The repository description and topics, from the wig's own fields.

    Identity fields feed labels. They carry real human casing and they are
    what somebody searches for, and GitHub's search is case insensitive, so
    what surfaces a repository is words on the page rather than the shape of
    the slug.
    """
    brand = facts.get("brand") or ""
    model = facts.get("model") or ""
    kind = facts.get("kind") or "device"
    name = " ".join(p for p in (brand, model) if p) or facts.get("name") or "device"

    description = (
        f"Home Assistant integration for {name} {kind} over infrared, "
        f"generated from a proven wig."
    )
    identifiers = facts.get("identifiers") or {}
    extra = ", ".join(
        f"{k.upper()} {v}" for k, v in identifiers.items() if k in ("upc", "asin")
    )
    if extra:
        description = f"{description[:-1]}. {extra}."

    topics = list(BASE_TOPICS)
    for value in (brand, kind, model, facts.get("protocol")):
        if not value:
            continue
        slug = topic_safe(value)
        if slug and slug not in topics:
            topics.append(slug)
    return description[:350], topics[:20]


def manifest_of(integration: Path) -> dict[str, Any]:
    candidates = sorted(integration.glob("custom_components/*/manifest.json"))
    if not candidates:
        raise Refusal(f"no custom_components manifest under {integration}")
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def run_the_gate(args: argparse.Namespace) -> dict[str, Any]:
    """Run the gate again, now, and refuse on anything but a pass."""
    command = [
        sys.executable,
        str(REPO_ROOT / "verify" / "verify_wig.py"),
        "--wig", args.wig,
        "--integration", str(args.integration),
        "--hair", str(args.hair),
        "--shop", str(args.shop),
        "--require-handles", str(PROMOTION_HANDLES),
        "--json",
    ]
    if args.exemption and Path(args.exemption).is_file():
        command += ["--exemption", str(args.exemption)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise Refusal(
            f"the gate did not produce a report:\n{result.stdout}{result.stderr}"
        ) from None
    if not payload.get("passed"):
        lines = "\n   ".join(payload.get("failures") or ["(no detail)"])
        raise Refusal(f"the gate refuses this build:\n   {lines}")
    return payload


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
        repo = args.repo or f"{stem}{MEDIUM_SUFFIX}"
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
        print(f"wig          {facts.get('content_hash', '?')}")
        if facts.get("shop_commit"):
            print(f"shop         WigShop@{str(facts['shop_commit'])[:7]}")
        print(f"accounts     {facts.get('promotion_handles', 0)} of {PROMOTION_HANDLES}"
              + ("  (waived, see EXEMPTIONS.md)" if facts.get("exemption") else ""))
        print(f"access       {github.how}")
        print()

        if not args.publish:
            print("DRY RUN. Nothing was created. Add --publish to do it.")
            return 0

        github.create_repo(repo, description, topics)
        push_initial_commit(
            args.integration,
            repo,
            f"{manifest.get('name', repo)}\n\n"
            f"Generated by WigFactory from {stem}, "
            f"content hash {facts.get('content_hash', 'unknown')}.",
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
