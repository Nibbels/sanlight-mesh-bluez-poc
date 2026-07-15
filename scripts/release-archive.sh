#!/usr/bin/env bash

set -euo pipefail

VERSION="${1:-}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || {
    echo "Usage: $0 VERSION" >&2
    echo "Example: $0 0.2.0" >&2
    exit 2
}

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

command -v git >/dev/null || { echo "ERROR: git is required" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "ERROR: sha256sum is required" >&2; exit 1; }
[[ -d .git ]] || { echo "ERROR: run from a Git checkout" >&2; exit 1; }
[[ -z "$(git status --short)" ]] || {
    echo "ERROR: worktree is not clean; commit or stash changes first" >&2
    exit 1
}

mkdir -p dist
name="sanlight-mesh-mqtt-gateway-${VERSION}"
archive="dist/${name}.tar.gz"
checksum="${archive}.sha256"

git archive \
    --format=tar.gz \
    --prefix="${name}/" \
    --output="$archive" \
    HEAD -- . \
    ':(exclude)private' \
    ':(exclude)dist'

forbidden='(^|/)(private/|\.state/|SANlightMesh\.json$|.*\.(log|pcap|pcapng)$|mqtt-password\.txt$|iobroker-mqtt-password\.txt$|sanlight-mesh-mqtt-gateway\.passwd$|sanlight-gateway-diagnostics-.*\.txt$|__pycache__/)'
if tar -tzf "$archive" | grep -E "$forbidden"; then
    echo "ERROR: release archive contains forbidden private/runtime files" >&2
    rm -f "$archive"
    exit 1
fi

(
    cd dist
    sha256sum "$(basename "$archive")" > "$(basename "$checksum")"
)

echo "Created $archive"
echo "Created $checksum"
cat "$checksum"
