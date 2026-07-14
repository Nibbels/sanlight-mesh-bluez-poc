#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop bluetooth.service bluetooth-mesh.service 2>/dev/null || true
sudo pkill -x bluetoothd 2>/dev/null || true
sudo pkill -x bluetooth-meshd 2>/dev/null || true
sudo rfkill unblock bluetooth
sudo rfkill unblock all
sudo hciconfig hci0 down 2>/dev/null || true
sudo btmgmt --index 0 power off 2>/dev/null || true

exec sudo /usr/libexec/bluetooth/bluetooth-meshd \
  --io generic:hci0 \
  --nodetach \
  --debug
