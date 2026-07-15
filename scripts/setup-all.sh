#!/usr/bin/env bash

set -euo pipefail
umask 077

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

CDB="$REPO_DIR/private/SANlightMesh.json"
STATE_DIR="$REPO_DIR/.state"
IV_INDEX=""
RESET_MESH_STATE=0
SKIP_PACKAGES=0
ALLOW_UNSUPPORTED=0

usage() {
    cat <<'USAGE'
Usage: sudo bash ./scripts/setup-all.sh [options]

Internal Mesh setup helper used by scripts/install-gateway.sh.
It validates or safely reconstructs protected project identity state before
allowing BlueZ imports. It never changes lamp time or brightness.

Options:
  --cdb PATH              private SANlight CDB (default: private/SANlightMesh.json)
  --state-dir PATH        protected project state directory (default: .state)
  --iv-index VALUE        independently verified Mesh IV Index
  --reset-mesh-state      explicitly clear local BlueZ/project state after preflight
  --skip-packages         do not run apt update/install
  --allow-unsupported     warn instead of failing outside the validated platform
  -h, --help              show this help
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cdb)
            [[ $# -ge 2 ]] || { echo "--cdb needs a path" >&2; exit 2; }
            CDB="$2"
            shift
            ;;
        --state-dir)
            [[ $# -ge 2 ]] || { echo "--state-dir needs a path" >&2; exit 2; }
            STATE_DIR="$2"
            shift
            ;;
        --iv-index)
            [[ $# -ge 2 ]] || { echo "--iv-index needs a value" >&2; exit 2; }
            IV_INDEX="$2"
            shift
            ;;
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
STATE_DIR="$(realpath -m "$STATE_DIR")"
install -d -m 0700 "$STATE_DIR"
CONTROL_STATE="$STATE_DIR/control-provisioner.json"
SENDER_STATE="$STATE_DIR/canonical-sender.json"

INSPECT_CLI=(
    python3 "$REPO_DIR/sanlight_canonical_sender_poc.py"
    --cdb "$CDB"
    --provisioner-state "$CONTROL_STATE"
    --sender-state "$SENDER_STATE"
)
[[ -n "$IV_INDEX" ]] && INSPECT_CLI+=(--iv-index "$IV_INDEX")

echo "[1/7] Validating private CDB without printing secrets..."
"${INSPECT_CLI[@]}" inspect

if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
    echo "[2/7] Installing validated Debian packages for Mesh and MQTT..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        bluez bluez-meshd dbus git procps python3 python3-dbus python3-gi \
        python3-paho-mqtt rfkill
else
    echo "[2/7] Package installation skipped by request."
fi

echo "[3/7] Running syntax and offline safety tests..."
bash "$REPO_DIR/scripts/run-tests.sh"

echo "[4/7] Checking the Raspberry Pi / BlueZ environment..."
CHECK_ARGS=()
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && CHECK_ARGS+=(--allow-unsupported)
bash "$REPO_DIR/scripts/sanlight-env-check.sh" "${CHECK_ARGS[@]}"

mesh_was_active=0
mqtt_was_active=0
systemctl is-active --quiet sanlight-meshd-generic.service 2>/dev/null && mesh_was_active=1 || true
systemctl is-active --quiet sanlight-mqtt-gateway.service 2>/dev/null && mqtt_was_active=1 || true

restore_previous_services() {
    local exit_code=$?
    trap - EXIT
    if [[ "$mesh_was_active" -eq 1 ]]; then
        systemctl start sanlight-meshd-generic.service 2>/dev/null || true
    else
        systemctl stop sanlight-meshd-generic.service 2>/dev/null || true
    fi
    if [[ "$mqtt_was_active" -eq 1 ]]; then
        systemctl start sanlight-mqtt-gateway.service 2>/dev/null || true
    else
        systemctl stop sanlight-mqtt-gateway.service 2>/dev/null || true
    fi
    exit "$exit_code"
}
trap restore_previous_services EXIT

# BlueZ writes node.json itself. Stop all project users before inspecting or
# reconstructing the token state so the database is not read mid-update.
systemctl stop sanlight-mqtt-gateway.service 2>/dev/null || true
systemctl stop sanlight-meshd-generic.service 2>/dev/null || true

if pgrep -x bluetooth-meshd >/dev/null 2>&1; then
    echo "ERROR: bluetooth-meshd is still running after the project services were stopped." >&2
    echo "Stop the conflicting Mesh daemon before identity-state inspection." >&2
    exit 1
fi

if [[ "$RESET_MESH_STATE" -eq 0 ]]; then
    echo "[5/7] Reconciling protected project state with exact BlueZ UUID paths..."
    RECOVERY_ARGS=(
        --cdb "$CDB"
        --state-dir "$STATE_DIR"
        --bluez-root /var/lib/bluetooth/mesh
    )
    [[ -n "$IV_INDEX" ]] && RECOVERY_ARGS+=(--iv-index "$IV_INDEX")
    EFFECTIVE_IV="$(PYTHONDONTWRITEBYTECODE=1 python3 -m sanlight_mesh.identity_recovery "${RECOVERY_ARGS[@]}")"
else
    echo "[5/7] Explicit reset requested; deriving the IV Index before clearing state..."
    EFFECTIVE_IV="$(PYTHONDONTWRITEBYTECODE=1 python3 - "$CDB" "$IV_INDEX" <<'PY_IV'
from pathlib import Path
import sys
from sanlight_mesh.cdb import load_mesh_material

cdb = Path(sys.argv[1])
explicit = sys.argv[2].strip()
material = load_mesh_material(cdb, 1)
if explicit:
    try:
        value = int(explicit, 0)
    except ValueError as exc:
        raise SystemExit("ERROR: --iv-index is not a valid integer") from exc
    if not 0 <= value <= 0xFFFFFFFF:
        raise SystemExit("ERROR: --iv-index is outside the uint32 range")
    if material.cdb_iv_index is not None and material.cdb_iv_index != value:
        raise SystemExit("ERROR: --iv-index disagrees with the CDB ivIndex")
else:
    value = material.cdb_iv_index
if value is None:
    raise SystemExit(
        "ERROR: no trusted IV Index is available; pass an independently verified --iv-index"
    )
print(value)
PY_IV
)"
fi

[[ "$EFFECTIVE_IV" =~ ^[0-9]+$ ]] || {
    echo "ERROR: identity preflight did not return a valid IV Index" >&2
    exit 1
}

echo "[6/7] Installing and starting the exclusive generic:hci0 Mesh service..."
SERVICE_ARGS=()
[[ "$RESET_MESH_STATE" -eq 1 ]] && SERVICE_ARGS+=(--reset-mesh-state)
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && SERVICE_ARGS+=(--allow-unsupported)
bash "$REPO_DIR/scripts/install-service.sh" "${SERVICE_ARGS[@]}"
if [[ "$RESET_MESH_STATE" -eq 1 && "$STATE_DIR" != "$REPO_DIR/.state" ]]; then
    rm -rf -- "$STATE_DIR"
    install -d -m 0700 "$STATE_DIR"
fi

echo "[7/7] Attaching or importing local BlueZ identities (no lamp writes)..."
CLI=(
    python3 "$REPO_DIR/sanlight_canonical_sender_poc.py"
    --cdb "$CDB"
    --iv-index "$EFFECTIVE_IV"
    --provisioner-state "$CONTROL_STATE"
    --sender-state "$SENDER_STATE"
)
"${CLI[@]}" setup

# setup-all.sh may be used directly during maintenance. Preserve a gateway that
# was running before the operation; the authoritative product installer will
# install/restart it separately for a fresh deployment.
if [[ "$mqtt_was_active" -eq 1 ]]; then
    systemctl restart sanlight-mqtt-gateway.service
fi

trap - EXIT

echo
echo "Mesh identity setup complete. No lamp time or brightness command was sent."
echo
"${CLI[@]}" list-nodes
