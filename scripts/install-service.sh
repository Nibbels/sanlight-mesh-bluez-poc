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

The generated systemd unit intentionally has no Bluetooth cleanup commands in ExecStartPre.
The cleanup is done by this installer before service start, because hciconfig/btmgmt can block under systemd.

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

find_cmd() {
  local cmd="$1"
  local path
  path="$(command -v "$cmd" 2>/dev/null || true)"
  if [[ -z "$path" ]]; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
  printf '%s\n' "$path"
}

find_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "ERROR: required path not found: $path" >&2
    exit 1
  fi
  printf '%s\n' "$path"
}

SYSTEMCTL="$(find_cmd systemctl)"
RFKILL="$(find_cmd rfkill)"
HCICONFIG="$(find_cmd hciconfig)"
BTMGMT="$(find_cmd btmgmt)"
BUSCTL="$(find_cmd busctl)"
PKILL="$(find_cmd pkill)"
MESHD="$(find_path /usr/libexec/bluetooth/bluetooth-meshd)"

if ! "$HCICONFIG" "$HCI" >/dev/null 2>&1; then
  echo "ERROR: Bluetooth controller '$HCI' was not found." >&2
  echo "Available controllers:" >&2
  "$HCICONFIG" -a >&2 || true
  exit 1
fi

if [[ "$HCI" =~ ^hci([0-9]+)$ ]]; then
  HCI_INDEX="${BASH_REMATCH[1]}"
else
  echo "ERROR: HCI controller must look like hci0, hci1, ...; got: $HCI" >&2
  exit 1
fi

echo "Repository: ${REPO_DIR}"
echo "Bluetooth controller: ${HCI}"
echo "Resolved commands:"
echo "  rfkill:          ${RFKILL}"
echo "  hciconfig:       ${HCICONFIG}"
echo "  btmgmt:          ${BTMGMT}"
echo "  bluetooth-meshd: ${MESHD}"
echo

echo "Stopping conflicting Bluetooth services/processes..."
"$SYSTEMCTL" stop bluetooth.service 2>/dev/null || true
"$SYSTEMCTL" stop bluetooth-mesh.service 2>/dev/null || true
"$SYSTEMCTL" stop "${SERVICE_NAME}.service" 2>/dev/null || true
"$SYSTEMCTL" reset-failed "${SERVICE_NAME}.service" 2>/dev/null || true
"$PKILL" -x bluetoothd 2>/dev/null || true
"$PKILL" -x bluetooth-meshd 2>/dev/null || true

echo "Unblocking Bluetooth and putting ${HCI} into a clean state..."
"$RFKILL" unblock bluetooth || true
"$RFKILL" unblock all || true
"$HCICONFIG" "$HCI" down 2>/dev/null || true
"$BTMGMT" --index "$HCI_INDEX" power off 2>/dev/null || true
"$RFKILL" unblock bluetooth || true

if [[ "$RESET_MESH_STATE" -eq 1 ]]; then
  echo "Resetting BlueZ mesh state under ${MESH_DIR} ..."
  mkdir -p "$MESH_DIR"
  rm -rf "${MESH_DIR:?}/"*
  echo "Removing local PoC state tokens under ${REPO_DIR} ..."
  rm -f "${REPO_DIR}"/.sanlight-mesh-poc-*-state.json
else
  echo "Keeping existing BlueZ mesh state under ${MESH_DIR}."
  echo "Keeping existing local PoC state tokens under ${REPO_DIR}."
fi

if [[ ! -f "${REPO_DIR}/private/SANlightMesh.json" ]]; then
  echo
  echo "NOTE: ${REPO_DIR}/private/SANlightMesh.json does not exist yet."
  echo "      Service installation can continue, but SANlight setup requires this file."
  echo
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
# Keep the unit itself minimal. Controller cleanup is done by install-service.sh
# before starting the service. Some Bluetooth helper commands can block when
# used as ExecStartPre under systemd.
ExecStart=${MESHD} --io generic:${HCI} --nodetach
Restart=on-failure
RestartSec=3
TimeoutStartSec=20

[Install]
WantedBy=multi-user.target
EOF

"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable "${SERVICE_NAME}.service"

if [[ "$START_SERVICE" -eq 1 ]]; then
  echo "Starting ${SERVICE_NAME}.service ..."
  if ! "$SYSTEMCTL" start "${SERVICE_NAME}.service"; then
    echo
    echo "ERROR: Service did not start. Recent logs:" >&2
    journalctl -u "${SERVICE_NAME}.service" -n 80 --no-pager >&2 || true
    exit 1
  fi

  sleep 2
  "$SYSTEMCTL" --no-pager --full status "${SERVICE_NAME}.service" || true
  echo
  echo "Checking D-Bus object org.bluez.mesh ..."
  if "$BUSCTL" tree org.bluez.mesh >/tmp/${SERVICE_NAME}.busctl 2>&1; then
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
