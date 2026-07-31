#!/usr/bin/env bash
# Fetch the read-only reference repositories the build workflow needs.
#
# Everything lands in reference/, which is gitignored. Re-running this is
# safe and cheap: an existing clone is fetched and hard reset to the remote
# rather than cloned again.
#
# Nothing in the build ever writes to reference/. See AGENTS.md rule 1.

set -euo pipefail

REF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reference"
mkdir -p "$REF_DIR"

# clone_or_update <url> <directory> <branch>
clone_or_update() {
    local url="$1" dir="$2" branch="$3"
    local path="$REF_DIR/$dir"

    if [ -d "$path/.git" ]; then
        echo "Updating $dir"
        git -C "$path" fetch --depth 1 origin "$branch"
        git -C "$path" checkout -q "$branch" 2>/dev/null || \
            git -C "$path" checkout -q -B "$branch" "origin/$branch"
        git -C "$path" reset -q --hard "origin/$branch"
    else
        echo "Cloning $dir"
        git clone --depth 1 --single-branch --branch "$branch" "$url" "$path"
    fi
}

# Home Assistant core is enormous and we want four directories out of it.
# Sparse checkout with a blobless filter keeps this to seconds rather than
# minutes. If the local git is too old for --sparse, fall back to a plain
# shallow clone rather than failing the setup.
clone_or_update_core() {
    local url="https://github.com/home-assistant/core.git"
    local path="$REF_DIR/home-assistant-core"
    local branch="dev"
    local paths=(
        homeassistant/components/infrared
        homeassistant/components/lg_infrared
        homeassistant/components/esphome
        homeassistant/helpers
    )

    if [ -d "$path/.git" ]; then
        echo "Updating home-assistant-core"
        git -C "$path" fetch --depth 1 origin "$branch"
        git -C "$path" reset -q --hard "origin/$branch"
        return
    fi

    echo "Cloning home-assistant-core (sparse)"
    if git clone --depth 1 --single-branch --branch "$branch" \
        --filter=blob:none --sparse "$url" "$path" 2>/dev/null; then
        git -C "$path" sparse-checkout set "${paths[@]}"
    else
        echo "  sparse clone unavailable, falling back to a shallow clone"
        git clone --depth 1 --single-branch --branch "$branch" "$url" "$path"
    fi
}

clone_or_update https://github.com/DAB-LABS/HAIR.git \
    HAIR main
clone_or_update https://github.com/DAB-LABS/WigShop.git \
    WigShop main
clone_or_update https://github.com/home-assistant-libs/infrared-protocols.git \
    infrared-protocols main
clone_or_update https://github.com/ludeeus/integration_blueprint.git \
    integration_blueprint main
clone_or_update_core

echo
echo "References ready in reference/. They are read only."

if [ -d "$REF_DIR/WigShop/.git" ]; then
    shop_sha="$(git -C "$REF_DIR/WigShop" rev-parse --short HEAD)"
    shop_date="$(git -C "$REF_DIR/WigShop" log -1 --format=%cs)"
    shop_count="$(find "$REF_DIR/WigShop/wigs" -name '*.wig.json' 2>/dev/null | wc -l | tr -d ' ')"
    echo "Wig Shop at $shop_sha ($shop_date), $shop_count wig(s) available."
fi

# The verification environment.
#
# HAIR's decoders use 3.12+ syntax (PEP 695 type parameters), so that is the
# floor. Anything newer is fine and newest is preferred. Naming one exact
# interpreter here was a mistake: python3.13 is not on every machine that has
# a perfectly good python3.14.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
for candidate in python3.15 python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
        'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
        >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

echo
if [ -z "$PY" ]; then
    echo "No Python 3.12 or newer found, so the verification environment was"
    echo "not created. HAIR's decoders need 3.12+ and the gate imports them."
    echo "On macOS:  brew install python@3.14"
    echo "Then re-run ./setup.sh."
    exit 0
fi

echo "Using $($PY --version) for the verification environment."
"$PY" -m venv "$REPO_ROOT/.venv"
"$REPO_ROOT/.venv/bin/pip" install --quiet --upgrade pip
if ! "$REPO_ROOT/.venv/bin/pip" install --quiet -r "$REPO_ROOT/verify/requirements.txt"; then
    echo
    echo "The verification dependencies did not install. The gate needs"
    echo "cryptography to check fitting signatures and reports invalid"
    echo "without it, so do not run a build until this is fixed."
    exit 1
fi

# Say which protocol set the gate will have. Upstream ships decoders for a
# few protocols and encoders for many; where it decodes, HAIR prefers it.
# Where it is absent the gate falls back to HAIR's own decoders, which is
# workable and narrower, and worth knowing before a run rather than after.
if "$REPO_ROOT/.venv/bin/python" -c 'import infrared_protocols' 2>/dev/null; then
    echo "Upstream infrared-protocols is present."
else
    echo "Upstream infrared-protocols is NOT present: it needs Python 3.14.2"
    echo "or newer and this environment is $($PY --version | cut -d' ' -f2)."
    echo "The gate falls back to HAIR's own decoders, which covers less."
fi

echo
echo "Ready. Verify a wig with:"
echo "  .venv/bin/python verify/verify_wig.py --wig <slug> --gate-only"
