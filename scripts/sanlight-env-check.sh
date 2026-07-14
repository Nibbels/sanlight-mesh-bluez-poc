#!/usr/bin/env bash
set -euo pipefail

ALLOW_UNSUPPORTED=0
if [[ "${1:-}" == "--allow-unsupported" ]]; then
    ALLOW_UNSUPPORTED=1
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--allow-unsupported]" >&2
    exit 2
fi

fail_or_warn() {
    if [[ "$ALLOW_UNSUPPORTED" -eq 1 ]]; then
        echo "WARNING: $*" >&2
    else
        echo "ERROR: $*" >&2
        exit 1
    fi
}

source /etc/os-release
[[ "${VERSION_CODENAME:-}" == "trixie" ]] || \
    fail_or_warn "validated OS is Debian/Raspberry Pi OS trixie; found ${VERSION_CODENAME:-unknown}."

[[ "$(getconf LONG_BIT)" == "64" ]] || \
    fail_or_warn "validated userspace is 64-bit."

case "$(uname -m)" in
    aarch64|arm64) ;;
    *) fail_or_warn "validated Raspberry Pi architecture is aarch64; found $(uname -m)." ;;
esac

for command in python3 busctl systemctl rfkill bluetoothd pkill; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $command" >&2
        exit 1
    }
done

MESHD=""
for candidate in \
    /usr/libexec/bluetooth/bluetooth-meshd \
    /usr/lib/bluetooth/bluetooth-meshd \
    /usr/sbin/bluetooth-meshd
do
    if [[ -x "$candidate" ]]; then
        MESHD="$candidate"
        break
    fi
done
[[ -n "$MESHD" ]] || {
    echo "ERROR: bluetooth-meshd executable not found; install bluez-meshd." >&2
    exit 1
}

BLUEZ_VERSION="$(bluetoothd --version 2>/dev/null || true)"
[[ "$BLUEZ_VERSION" == "5.82" ]] || \
    fail_or_warn "validated BlueZ version is 5.82; found ${BLUEZ_VERSION:-unknown}."

python3 - <<'PY'
import dbus
from gi.repository import GLib
print("Python D-Bus/GLib imports: OK")
PY

[[ -e /sys/class/bluetooth/hci0 ]] || {
    echo "ERROR: hci0 is not present under /sys/class/bluetooth." >&2
    exit 1
}

echo "OS: ${PRETTY_NAME}"
echo "Architecture: $(uname -m), $(getconf LONG_BIT)-bit userspace"
echo "BlueZ: ${BLUEZ_VERSION}"
echo "bluetooth-meshd: ${MESHD}"
echo "rfkill: $(command -v rfkill)"
echo "Bluetooth controller hci0: present"
echo "Environment check: OK"
