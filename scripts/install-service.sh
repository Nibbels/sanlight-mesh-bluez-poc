#!/usr/bin/env bash
set -euo pipefail
umask 077

RESET_MESH_STATE=0
ALLOW_UNSUPPORTED=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --reset-mesh-state) RESET_MESH_STATE=1 ;;
        --allow-unsupported) ALLOW_UNSUPPORTED=1 ;;
        -h|--help)
            echo "Usage: sudo $0 [--reset-mesh-state] [--allow-unsupported]"
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ "$EUID" -ne 0 ]]; then
    SUDO_ARGS=()
    [[ "$RESET_MESH_STATE" -eq 1 ]] && SUDO_ARGS+=(--reset-mesh-state)
    [[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && SUDO_ARGS+=(--allow-unsupported)
    exec sudo -- bash "$0" "${SUDO_ARGS[@]}"
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

CHECK_ARGS=()
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && CHECK_ARGS+=(--allow-unsupported)
bash "$REPO_DIR/scripts/sanlight-env-check.sh" "${CHECK_ARGS[@]}"

install -d -m 0755 /usr/local/libexec
install -m 0755 \
    "$REPO_DIR/scripts/start-meshd-generic.sh" \
    /usr/local/libexec/sanlight-meshd-generic-start
install -m 0644 \
    "$REPO_DIR/systemd/sanlight-meshd-generic.service.example" \
    /etc/systemd/system/sanlight-meshd-generic.service

install -d -m 0700 /var/lib/bluetooth/mesh

systemctl stop sanlight-meshd-generic.service 2>/dev/null || true
systemctl disable --now bluetooth-mesh.service 2>/dev/null || true
systemctl disable --now bluetooth.service 2>/dev/null || true
pkill -x bluetooth-meshd 2>/dev/null || true
pkill -x bluetoothd 2>/dev/null || true

if [[ "$RESET_MESH_STATE" -eq 1 ]]; then
    echo "Reset requested: removing local bluetooth-meshd and project token state."
    install -d -m 0700 /var/lib/bluetooth/mesh
    find /var/lib/bluetooth/mesh -mindepth 1 -delete
    rm -rf -- "$REPO_DIR/.state"
    rm -f -- "$REPO_DIR"/.sanlight-mesh-poc-*-state.json
    install -d -m 0700 "$REPO_DIR/.state"
fi

systemctl daemon-reload
systemctl reset-failed sanlight-meshd-generic.service || true
systemctl enable sanlight-meshd-generic.service
systemctl start --no-block sanlight-meshd-generic.service

READY=0
for _ in $(seq 1 25); do
    if systemctl is-active --quiet sanlight-meshd-generic.service \
        && busctl tree org.bluez.mesh /org/bluez/mesh >/dev/null 2>&1; then
        READY=1
        break
    fi
    if systemctl is-failed --quiet sanlight-meshd-generic.service; then
        break
    fi
    sleep 1
done

if [[ "$READY" -ne 1 ]]; then
    echo "ERROR: org.bluez.mesh was not ready within 25 seconds." >&2
    echo "Recent service status:" >&2
    systemctl --no-pager --full status sanlight-meshd-generic.service >&2 || true
    echo "Recent service log:" >&2
    journalctl --no-pager -u sanlight-meshd-generic.service -n 80 >&2 || true
    exit 1
fi

echo "sanlight-meshd-generic.service: active and org.bluez.mesh is ready."
