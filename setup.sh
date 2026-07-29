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

echo "Next: python3.13 -m venv .venv && .venv/bin/pip install -r verify/requirements.txt"
