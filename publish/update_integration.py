#!/usr/bin/env python3
"""Carry a factory change into a repository that is already published.

The other tool creates. This one updates, and they are separate commands
because their preconditions are opposites: creating refuses if the repository
exists, updating refuses if it does not.

Updating is the common case once a few integrations are out. A wig gets
refitted, combed, or repaired; the send count moves; the stamp goes stale. The
factory tree changes and that change has to reach the published repository
without anybody assembling git commands by hand, because assembling them by
hand is the bottleneck a factory exists to remove.

Two rules make it safe to run unattended.

**It never pushes to the default branch.** Every change arrives as a pull
request. A published integration accrues commits the factory never saw, and a
pull request is where that becomes visible before it becomes a problem.

**It never deletes.** Files the factory generates are overwritten; files that
exist only in the published repository are left exactly where they are and
reported. Somebody adding a CONTRIBUTING or a second workflow should not have
it quietly removed by a stamp refresh.

    publish/update_integration.py --wig SLUG --integration PATH
    publish/update_integration.py --wig SLUG --integration PATH --push
    publish/update_integration.py --wig SLUG --integration PATH --push --merge
"""

from __future__ import annotations

import argparse
import filecmp
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
    git,
    manifest_of,
    repo_name_for,
    run_the_gate,
)

SKIP = {".git", "__pycache__", ".DS_Store"}


def _walk(root: Path) -> set[Path]:
    """Every file under ``root``, relative, ignoring noise."""
    found: set[Path] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP for part in rel.parts):
            continue
        found.add(rel)
    return found


def compare(factory: Path, published: Path) -> dict[str, list[str]]:
    """What this update would change, in three buckets."""
    ours, theirs = _walk(factory), _walk(published)
    changed = sorted(
        str(p)
        for p in ours & theirs
        if not filecmp.cmp(factory / p, published / p, shallow=False)
    )
    return {
        "changed": changed,
        "added": sorted(str(p) for p in ours - theirs),
        "theirs_only": sorted(str(p) for p in theirs - ours),
    }


def apply_factory_tree(factory: Path, published: Path) -> None:
    """Overwrite what the factory owns. Never remove what it does not."""
    for rel in sorted(_walk(factory)):
        target = published / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(factory / rel, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update a published integration.")
    parser.add_argument("--wig", required=True, help="shop slug or path")
    parser.add_argument("--integration", required=True, type=Path)
    parser.add_argument("--hair", type=Path, default=DEFAULT_HAIR)
    parser.add_argument("--shop", type=Path, default=DEFAULT_SHOP)
    parser.add_argument("--exemption", type=Path, default=REPO_ROOT / "EXEMPTIONS.md")
    parser.add_argument("--repo", help="override the derived repository name")
    parser.add_argument("--branch", help="override the branch name")
    parser.add_argument(
        "--push", action="store_true", help="open the pull request"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="with --push, also merge it and cut the release",
    )
    args = parser.parse_args(argv)

    try:
        report = run_the_gate(args)
        facts = report.get("facts") or {}
        repo = args.repo or repo_name_for(args.wig)
        manifest = manifest_of(args.integration)
        version = str(manifest.get("version", "0.0.0"))
        tag = f"v{version}"

        github = GitHub(dry_run=not args.push)

        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / repo
            subprocess.run(  # noqa: S603
                ["git", "clone", "--quiet",
                 f"https://github.com/{OWNER}/{repo}.git", str(clone)],
                capture_output=True, text=True, check=False,
            )
            if not (clone / ".git").is_dir():
                raise Refusal(
                    f"could not clone {OWNER}/{repo}. This tool updates a "
                    f"published integration; use publish_integration.py to "
                    f"create one."
                )
            # The clone is the authority on both questions the API would have
            # been asked: it exists, and this is its default branch.
            base = git(clone, "rev-parse", "--abbrev-ref", "HEAD")

            published_version = str(
                manifest_of(clone).get("version", "0.0.0")
            )
            diff = compare(args.integration.resolve(), clone)
            touched = diff["changed"] + diff["added"]

            print(f"repository   {OWNER}/{repo}, base {base}")
            print(f"version      {published_version} published, "
                  f"{version} in the factory")
            print(f"history      {git(clone, 'rev-list', '--count', base)} "
                  f"commit(s) on {base}")
            print()
            if not touched:
                print("Nothing to update. The published repository already "
                      "matches the factory tree.")
                return 0
            for label, key in (("changed", "changed"), ("new", "added")):
                if diff[key]:
                    print(f"  {label}: {', '.join(diff[key])}")
            if diff["theirs_only"]:
                print(f"  left alone (not the factory's): "
                      f"{', '.join(diff['theirs_only'])}")
            print()

            if version == published_version:
                raise Refusal(
                    f"the factory would change {len(touched)} file(s) but the "
                    f"manifest version is still {version}. Home Assistant "
                    f"shows that number to users and HACS tracks the release "
                    f"tag, so shipping a change without moving it means "
                    f"somebody's install quietly stops matching what it says "
                    f"it is. Bump it in the factory tree first."
                )
            if tag in git(clone, "tag", "--list").splitlines():
                raise Refusal(f"{tag} already exists in {OWNER}/{repo}")

            if not args.push:
                print("DRY RUN. Nothing was pushed. Add --push to open the "
                      "pull request.")
                return 0

            branch = args.branch or f"factory-{version}"
            git(clone, "checkout", "-q", "-b", branch)
            apply_factory_tree(args.integration.resolve(), clone)
            git(clone, "add", "-A")
            git(
                clone,
                "-c", "user.name=WigFactory",
                "-c", "user.email=noreply@localhost",
                "commit", "-q", "-m",
                f"Update to {version} from the factory\n\n"
                f"Wig {facts.get('content_hash', 'unknown')} at "
                f"WigShop@{str(facts.get('shop_commit') or '')[:7]}.\n"
                f"Send count {facts.get('default_send_count', '?')}, proven "
                f"threshold "
                f"{(facts.get('send_times') or {}).get('derived', 'unrecorded')}.",
            )
            git(clone, "push", "-q", "-u", "origin", branch)

            _, topics = describe(facts)
            body = (
                f"Generated by WigFactory and gated before this branch "
                f"existed.\n\n"
                f"- Wig content hash `{facts.get('content_hash', '?')}`\n"
                f"- Wig Shop `{str(facts.get('shop_commit') or '?')[:7]}`\n"
                f"- Send count {facts.get('default_send_count', '?')} against a "
                f"proven threshold of "
                f"{(facts.get('send_times') or {}).get('derived', 'unrecorded')}\n"
                f"- Version {published_version} to {version}\n\n"
                f"Files the factory does not own were left untouched.\n"
            )
            url = github.create_pr(
                repo, branch, base, f"Update to {version} from the factory", body
            )
            print(f"PULL REQUEST  {url}")

            if args.merge:
                github.merge_pr(repo, branch)
                github.create_release(repo, tag)
                print(f"MERGED and released {tag}")
            else:
                print("Review it, then merge and cut the release, or rerun "
                      "with --merge to do both.")
        return 0
    except Refusal as err:
        print(f"REFUSED: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
