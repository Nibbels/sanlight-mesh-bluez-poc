#!/usr/bin/env bash
set -euo pipefail

echo '== OS =='
uname -a
cat /etc/os-release | sed -n '1,8p'

echo '== BlueZ =='
bluetoothd --version || true
dpkg -l | grep -E 'bluez|bluez-meshd|bluez-firmware|linux-image|raspi-firmware' || true

echo '== Controller =='
rfkill list all || true
hciconfig -a || true
btmgmt info || true

echo '== Mesh daemon path =='
ls -l /usr/libexec/bluetooth/bluetooth-meshd || true
/usr/libexec/bluetooth/bluetooth-meshd --help 2>&1 | sed -n '1,80p' || true
