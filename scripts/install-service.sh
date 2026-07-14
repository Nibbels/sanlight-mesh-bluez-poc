#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="sanlight-meshd-generic"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MESH_DIR="/var/lib/bluetooth/mesh"

usage() {
  cat <<'USAGE'
Install and start the SANlight BlueZ Mesh daemon service.

Usage:
  sudo ./scripts/install-service.sh [options]

Options:
  --hci hci0           Bluetooth controller to use. Default: hci0
  --reset-mesh-state   Delete /var/lib/bluetooth/mesh/* before starting.
                       Use only for a fresh import/setup or development reset.
  --no-start           Install service but do not start it.
  --help               Show this help.

What this script does:
  - checks required commands/packages
  - stops bluetooth.service, bluetooth-mesh.service and old bluetooth-meshd processes
  - unblocks Bluetooth via rfkill
  - installs a systemd service using bluetooth-meshd --io generic:<hci>
  - enables the service for reboot
  - starts it immediately unless --no-start is used

It does not copy or modify private/SANlightMesh.json.
It does not run the Python 'setup' command.
USAGE
}

HCI="hci0"
RESET_MESH_STATE=0
START_SERVICE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hci)
      HCI="${2:-}"
      if [[ -z "$HCI" ]]; then
        echo "ERROR: --hci requires a value, for example hci0" >&2
        exit 2
      fi
      shift 2
      ;;
    --reset-mesh-state)
      RESET_MESH_STATE=1
      shift
      ;;
    --no-start)
      START_SERVICE=0
      shift
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
  echo "  sudo ./scripts/install-service.sh" >&2
  exit 1
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "ERROR: required path not found: $path" >&2
    exit 1
  fi
}

require_cmd systemctl
require_cmd rfkill
require_cmd hciconfig
require_cmd btmgmt
require_cmd busctl
require_path /usr/libexec/bluetooth/bluetooth-meshd

if ! hciconfig "$HCI" >/dev/null 2>&1; then
  echo "ERROR: Bluetooth controller '$HCI' was not found." >&2
  echo "Available controllers:" >&2
  hciconfig -a >&2 || true
  exit 1
fi

echo "Repository: ${REPO_DIR}"
echo "Bluetooth controller: ${HCI}"
echo

echo "Stopping conflicting Bluetooth services/processes..."
systemctl stop bluetooth.service 2>/dev/null || true
systemctl stop bluetooth-mesh.service 2>/dev/null || true
systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
pkill -x bluetoothd 2>/dev/null || true
pkill -x bluetooth-meshd 2>/dev/null || true

echo "Unblocking Bluetooth and putting ${HCI} into a clean state..."
rfkill unblock bluetooth || true
rfkill unblock all || true
hciconfig "$HCI" down 2>/dev/null || true
btmgmt --index "${HCI#hci}" power off 2>/dev/null || true
rfkill unblock bluetooth || true

if [[ "$RESET_MESH_STATE" -eq 1 ]]; then
  echo "Resetting BlueZ mesh state under ${MESH_DIR} ..."
  mkdir -p "$MESH_DIR"
  rm -rf "${MESH_DIR:?}/"*
else
  echo "Keeping existing BlueZ mesh state under ${MESH_DIR}."
fi

echo "Installing systemd service: ${SERVICE_FILE}"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=SANlight BlueZ Mesh Daemon using generic HCI
Documentation=https://github.com/Nibbels/sanlight-mesh-bluez-poc
After=network-online.target
Wants=network-online.target
Conflicts=bluetooth.service bluetooth-mesh.service

[Service]
Type=simple
ExecStartPre=/usr/bin/rfkill unblock bluetooth
ExecStartPre=-/usr/sbin/hciconfig ${HCI} down
ExecStartPre=-/usr/bin/btmgmt --index ${HCI#hci} power off
ExecStart=/usr/libexec/bluetooth/bluetooth-meshd --io generic:${HCI} --nodetach
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

if [[ "$START_SERVICE" -eq 1 ]]; then
  echo "Starting ${SERVICE_NAME}.service ..."
  systemctl start "${SERVICE_NAME}.service"
  sleep 2
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
  echo
  echo "Checking D-Bus object org.bluez.mesh ..."
  if busctl tree org.bluez.mesh >/tmp/${SERVICE_NAME}.busctl 2>&1; then
    cat /tmp/${SERVICE_NAME}.busctl
    echo
    echo "OK: org.bluez.mesh is visible."
  else
    cat /tmp/${SERVICE_NAME}.busctl || true
    echo
    echo "WARNING: org.bluez.mesh is not visible yet. Check logs with:" >&2
    echo "  journalctl -u ${SERVICE_NAME}.service -n 100 --no-pager" >&2
  fi
fi

cat <<EOF

Next steps:

1) Put your SANlight CDB here:
   ${REPO_DIR}/private/SANlightMesh.json

2) Check detected lamp node addresses:
   cd ${REPO_DIR}
   python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes

3) Run setup once after a fresh install/reset:
   sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json --iv-index 0 setup

4) Test:
   sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now

Useful logs:
   journalctl -u ${SERVICE_NAME}.service -f

EOF
