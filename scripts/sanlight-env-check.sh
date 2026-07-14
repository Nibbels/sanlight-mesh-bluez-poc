#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="sanlight-meshd-generic"

echo "== OS =="
cat /etc/os-release | sed -n '1,8p'
echo

echo "== Kernel =="
uname -a
echo

echo "== BlueZ =="
if command -v bluetoothd >/dev/null 2>&1; then
  bluetoothd --version || true
else
  echo "bluetoothd not found"
fi
if command -v bluetooth-meshd >/dev/null 2>&1; then
  command -v bluetooth-meshd
elif [[ -x /usr/libexec/bluetooth/bluetooth-meshd ]]; then
  echo "/usr/libexec/bluetooth/bluetooth-meshd"
else
  echo "bluetooth-meshd not found"
fi
echo

echo "== Bluetooth controllers =="
hciconfig -a || true
echo

echo "== rfkill =="
rfkill list all || true
echo

echo "== systemd service =="
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
echo

echo "== org.bluez.mesh on D-Bus =="
busctl tree org.bluez.mesh || true
echo

echo "== Recent service logs =="
journalctl -u "${SERVICE_NAME}.service" -n 80 --no-pager || true
