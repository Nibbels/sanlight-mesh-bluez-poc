#!/usr/bin/env bash
set -euo pipefail
umask 077

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

CDB="$REPO_DIR/private/SANlightMesh.json"
IV_INDEX=""
RESET_MESH_STATE=0
SKIP_PACKAGES=0
ALLOW_UNSUPPORTED=0

usage() {
    cat <<USAGE
Usage: sudo bash ./scripts/setup-all.sh [options]

Options:
  --cdb PATH              private SANlight CDB (default: private/SANlightMesh.json)
  --iv-index VALUE        verified Mesh IV Index; required when absent from CDB
  --reset-mesh-state      explicitly clear local BlueZ/project state after preflight
  --skip-packages         do not run apt update/install
  --allow-unsupported     warn instead of failing outside the validated platform
  -h, --help              show this help

Setup configures local BlueZ identities only. It never changes lamp time or brightness.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cdb) [[ $# -ge 2 ]] || { echo "--cdb needs a path" >&2; exit 2; }; CDB="$2"; shift ;;
        --iv-index) [[ $# -ge 2 ]] || { echo "--iv-index needs a value" >&2; exit 2; }; IV_INDEX="$2"; shift ;;
        --reset-mesh-state) RESET_MESH_STATE=1 ;;
        --skip-packages) SKIP_PACKAGES=1 ;;
        --allow-unsupported) ALLOW_UNSUPPORTED=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ "$EUID" -ne 0 ]]; then
    echo "Please run this setup with sudo." >&2
    exit 1
fi

CDB="$(realpath -m "$CDB")"
[[ -f "$CDB" ]] || {
    echo "ERROR: CDB not found: $CDB" >&2
    echo "Copy SANlightMesh.json to private/ and never commit it." >&2
    exit 1
}

if [[ "$CDB" == "$REPO_DIR/private/"* ]]; then
    install -d -m 0700 "$REPO_DIR/private"
fi
chmod 0600 "$CDB"
install -d -m 0700 "$REPO_DIR/.state"

CLI=(python3 "$REPO_DIR/sanlight_canonical_sender_poc.py" --cdb "$CDB")
if [[ -n "$IV_INDEX" ]]; then
    CLI+=(--iv-index "$IV_INDEX")
fi

# Destructive actions are deliberately after semantic CDB validation and tests.
echo "[1/6] Validating private CDB without printing secrets..."
"${CLI[@]}" inspect

if [[ -z "$IV_INDEX" ]]; then
    CDB_IV="$(python3 - "$CDB" <<'PY_IV'
import sys
from pathlib import Path
from sanlight_mesh.cdb import load_mesh_material
value = load_mesh_material(Path(sys.argv[1]), 1).cdb_iv_index
print("" if value is None else value)
PY_IV
)"
    if [[ -z "$CDB_IV" ]]; then
        echo "ERROR: this CDB has no ivIndex." >&2
        echo "Rerun with the independently verified current value, for example:" >&2
        echo "  sudo bash ./scripts/setup-all.sh --iv-index 0" >&2
        echo "Do not assume 0 for an unrelated Mesh." >&2
        exit 1
    fi
fi

echo "[2/6] Running syntax and offline safety tests..."
bash "$REPO_DIR/scripts/run-tests.sh"

if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
    echo "[3/6] Installing validated Debian packages..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        bluez bluez-meshd dbus git procps python3 python3-dbus python3-gi rfkill
else
    echo "[3/6] Package installation skipped by request."
fi

echo "[4/6] Checking the Raspberry Pi / BlueZ environment..."
CHECK_ARGS=()
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && CHECK_ARGS+=(--allow-unsupported)
bash "$REPO_DIR/scripts/sanlight-env-check.sh" "${CHECK_ARGS[@]}"

echo "[5/6] Installing and starting the exclusive generic:hci0 Mesh service..."
SERVICE_ARGS=()
[[ "$RESET_MESH_STATE" -eq 1 ]] && SERVICE_ARGS+=(--reset-mesh-state)
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && SERVICE_ARGS+=(--allow-unsupported)
bash "$REPO_DIR/scripts/install-service.sh" "${SERVICE_ARGS[@]}"

echo "[6/6] Configuring local BlueZ identities (no lamp write commands)..."
"${CLI[@]}" setup

echo
echo "Setup complete. No lamp time or brightness command was sent."
echo
"${CLI[@]}" list-nodes
