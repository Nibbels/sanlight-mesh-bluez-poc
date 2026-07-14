#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDB="${REPO_DIR}/private/SANlightMesh.json"
INSTALL_SERVICE="${REPO_DIR}/scripts/install-service.sh"
PY="${PYTHON:-python3}"

usage() {
  cat <<'USAGE'
Run the complete first-time SANlight Mesh PoC setup.

Usage:
  sudo bash ./scripts/setup-all.sh [options]

Options:
  --keep-state      Do not reset BlueZ mesh state or local PoC state tokens.
                    Default is a clean local reset, which is best for first setup.
  --hci hci0        Bluetooth controller to use. Default: hci0
  --help            Show this help.

What this script does:
  - checks that private/SANlightMesh.json exists
  - checks Python syntax
  - installs/starts sanlight-meshd-generic.service
  - resets local BlueZ/Python state by default
  - runs the Python mesh import/setup
  - prints detected lamp nodes

It does not change lamp brightness or lamp time.
USAGE
}

RESET=1
HCI="hci0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-state)
      RESET=0
      shift
      ;;
    --hci)
      HCI="${2:-}"
      if [[ -z "$HCI" ]]; then
        echo "ERROR: --hci requires a value, for example hci0" >&2
        exit 2
      fi
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root, for example:" >&2
  echo "  sudo bash ./scripts/setup-all.sh" >&2
  exit 1
fi

if [[ ! -f "$CDB" ]]; then
  cat >&2 <<EOF
ERROR: SANlight CDB file not found:

  ${CDB}

Export SANlightMesh.json from the SANlight smartphone app and copy it to:

  ${REPO_DIR}/private/SANlightMesh.json

Then run this script again.
EOF
  exit 1
fi

echo "Repository: ${REPO_DIR}"
echo "CDB: ${CDB}"
echo "Bluetooth controller: ${HCI}"
echo

echo "Checking Python syntax..."
"$PY" -m py_compile \
  "${REPO_DIR}/sanlight_protocol.py" \
  "${REPO_DIR}/sanlight_canonical_sender_poc.py"

echo
echo "Installing and starting BlueZ mesh service..."
if [[ "$RESET" -eq 1 ]]; then
  bash "$INSTALL_SERVICE" --hci "$HCI" --reset-mesh-state
else
  bash "$INSTALL_SERVICE" --hci "$HCI"
fi

echo
echo "Running SANlight mesh import/setup..."
"$PY" "${REPO_DIR}/sanlight_canonical_sender_poc.py" \
  --cdb "$CDB" \
  --iv-index 0 \
  setup

echo
echo "Detected SANlight nodes:"
"$PY" "${REPO_DIR}/sanlight_canonical_sender_poc.py" \
  --cdb "$CDB" \
  list-nodes

cat <<EOF

Setup complete.

Useful next commands:

  sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now
  sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json get-live <NODE>
  journalctl -u sanlight-meshd-generic.service -f

EOF
