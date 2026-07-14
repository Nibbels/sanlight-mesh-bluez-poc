#!/bin/sh
set -eu
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

# rfkill is /usr/sbin/rfkill on Debian, but use PATH discovery to avoid a
# distribution-specific hard-coded location.
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock bluetooth || true
fi

if [ ! -e /sys/class/bluetooth/hci0 ]; then
    echo "ERROR: Bluetooth controller hci0 is not available." >&2
    exit 1
fi

for candidate in \
    /usr/libexec/bluetooth/bluetooth-meshd \
    /usr/lib/bluetooth/bluetooth-meshd \
    /usr/sbin/bluetooth-meshd
do
    if [ -x "$candidate" ]; then
        MESHD="$candidate"
        break
    fi
done

if [ -z "${MESHD:-}" ]; then
    echo "ERROR: bluetooth-meshd executable was not found." >&2
    exit 1
fi

exec "$MESHD" --io generic:hci0 --nodetach
