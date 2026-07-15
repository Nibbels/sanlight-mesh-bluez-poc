#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

GATEWAY_ID="sanlight-pi"
PORT="1883"
BIND_ADDRESS="0.0.0.0"
SKIP_PACKAGES=0
RESET_PASSWORDS=0
ASSUME_YES=0

GATEWAY_USER="sanlight-gateway"
IOBROKER_USER="sanlight-iobroker"
CONFIG_PATH="/etc/mosquitto/conf.d/sanlight-mesh-gateway.conf"
PASSWORD_PATH="/etc/mosquitto/sanlight-mesh-passwords"
ACL_PATH="/etc/mosquitto/sanlight-mesh-acl"

usage() {
    cat <<'EOF_USAGE'
Usage: sudo bash scripts/install-mosquitto-broker.sh [options]

Install and configure a dedicated Mosquitto broker endpoint for one SANlight
Mesh MQTT gateway and one ioBroker MQTT client.

Run this on the broker/ioBroker host, not on the lamp-side gateway host.
The default listener is password-authenticated but not TLS-encrypted and is
intended only for a trusted private LAN.

Options:
  --gateway-id ID         MQTT gateway ID/topic namespace (default: sanlight-pi)
  --port PORT             broker listener port (default: 1883)
  --bind-address ADDRESS  listener address (default: 0.0.0.0)
  --reset-passwords       rotate both managed MQTT-user passwords
  --skip-packages         do not run apt update/install
  --yes                   accept the trusted-LAN warning non-interactively
  -h, --help              show this help
EOF_USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gateway-id)
            [[ $# -ge 2 ]] || { echo "ERROR: --gateway-id requires a value" >&2; exit 2; }
            GATEWAY_ID="$2"
            shift
            ;;
        --port)
            [[ $# -ge 2 ]] || { echo "ERROR: --port requires a value" >&2; exit 2; }
            PORT="$2"
            shift
            ;;
        --bind-address)
            [[ $# -ge 2 ]] || { echo "ERROR: --bind-address requires a value" >&2; exit 2; }
            BIND_ADDRESS="$2"
            shift
            ;;
        --reset-passwords)
            RESET_PASSWORDS=1
            ;;
        --skip-packages)
            SKIP_PACKAGES=1
            ;;
        --yes)
            ASSUME_YES=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

[[ "$GATEWAY_ID" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || {
    echo "ERROR: gateway ID must match [a-z0-9][a-z0-9_-]{0,47}" >&2
    exit 2
}

[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || {
    echo "ERROR: port must be in the range 1..65535" >&2
    exit 2
}

[[ -n "$BIND_ADDRESS" && "$BIND_ADDRESS" != *[[:space:]]* ]] || {
    echo "ERROR: bind address must be a single non-empty value" >&2
    exit 2
}

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: run this script with sudo." >&2
    exit 1
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
    cat <<EOF_WARNING
This will create a password-authenticated, non-TLS MQTT listener on
${BIND_ADDRESS}:${PORT}. Credentials and MQTT payloads are not encrypted on the
network. Continue only on a trusted private LAN or add a reviewed TLS setup.
EOF_WARNING
    read -r -p "Continue? [y/N]: " answer
    case "${answer,,}" in
        y|yes) ;;
        *) echo "Cancelled."; exit 1 ;;
    esac
fi

if [[ "$SKIP_PACKAGES" -ne 1 ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y mosquitto mosquitto-clients
fi

for command in mosquitto_passwd mosquitto_pub systemctl ss grep install mktemp cmp find xargs awk timeout; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "ERROR: required command is unavailable: $command" >&2
        exit 1
    }
done

install -d -o root -g root -m 0755 /etc/mosquitto/conf.d

conflicts="$({
    grep -HEn \
        '^[[:space:]]*(listener|allow_anonymous|password_file|acl_file)[[:space:]]' \
        /etc/mosquitto/mosquitto.conf \
        2>/dev/null \
        || true
    find /etc/mosquitto/conf.d -maxdepth 1 -type f -name '*.conf' ! -path "$CONFIG_PATH" -print0 \
        | xargs -0 -r grep -HEn '^[[:space:]]*(listener|allow_anonymous|password_file|acl_file)[[:space:]]' \
        || true
} 2>/dev/null)"

if [[ -n "$conflicts" ]]; then
    echo "ERROR: another Mosquitto listener/authentication configuration exists:" >&2
    printf '%s\n' "$conflicts" >&2
    echo "Refusing to merge automatically. Review the existing broker configuration." >&2
    exit 1
fi

stamp="$(date --utc +%Y%m%dT%H%M%SZ)"
backup_file() {
    local path="$1"
    if [[ -f "$path" ]]; then
        cp -a -- "$path" "${path}.backup-${stamp}"
    fi
}

password_tmp=""
config_tmp=""
acl_tmp=""
cleanup() {
    [[ -z "$password_tmp" ]] || rm -f -- "$password_tmp"
    [[ -z "$config_tmp" ]] || rm -f -- "$config_tmp"
    [[ -z "$acl_tmp" ]] || rm -f -- "$acl_tmp"
}
trap cleanup EXIT

create_password_file() {
    password_tmp="$(mktemp)"
    chmod 0600 "$password_tmp"

    echo "Set the password used by the SANlight gateway (${GATEWAY_USER})."
    mosquitto_passwd -c "$password_tmp" "$GATEWAY_USER"

    echo "Set the separate password used by ioBroker (${IOBROKER_USER})."
    mosquitto_passwd "$password_tmp" "$IOBROKER_USER"

    install -o root -g mosquitto -m 0640 "$password_tmp" "$PASSWORD_PATH"
    rm -f -- "$password_tmp"
    password_tmp=""
}

if [[ "$RESET_PASSWORDS" -eq 1 ]]; then
    backup_file "$PASSWORD_PATH"
    create_password_file
elif [[ ! -f "$PASSWORD_PATH" ]]; then
    create_password_file
else
    chown root:mosquitto "$PASSWORD_PATH"
    chmod 0640 "$PASSWORD_PATH"

    missing_user=0
    for user in "$GATEWAY_USER" "$IOBROKER_USER"; do
        if ! grep -Eq "^${user}:" "$PASSWORD_PATH"; then
            if [[ "$missing_user" -eq 0 ]]; then
                backup_file "$PASSWORD_PATH"
                missing_user=1
            fi
            echo "Set the password for the missing managed MQTT user (${user})."
            mosquitto_passwd "$PASSWORD_PATH" "$user"
        fi
    done
fi

acl_tmp="$(mktemp)"
cat >"$acl_tmp" <<EOF_ACL
# Managed by scripts/install-mosquitto-broker.sh
# Gateway publishes verified state/results and reads only its command topic.
user ${GATEWAY_USER}
topic read sanlightmesh/v1/${GATEWAY_ID}/command
topic write sanlightmesh/v1/${GATEWAY_ID}/availability
topic write sanlightmesh/v1/${GATEWAY_ID}/gateway/#
topic write sanlightmesh/v1/${GATEWAY_ID}/nodes/#
topic write sanlightmesh/v1/${GATEWAY_ID}/result/#

# ioBroker observes state/results and may publish only fresh commands.
user ${IOBROKER_USER}
topic write sanlightmesh/v1/${GATEWAY_ID}/command
topic read sanlightmesh/v1/${GATEWAY_ID}/availability
topic read sanlightmesh/v1/${GATEWAY_ID}/gateway/#
topic read sanlightmesh/v1/${GATEWAY_ID}/nodes/#
topic read sanlightmesh/v1/${GATEWAY_ID}/result/#
EOF_ACL

if [[ ! -f "$ACL_PATH" ]] || ! cmp -s "$acl_tmp" "$ACL_PATH"; then
    backup_file "$ACL_PATH"
    install -o root -g mosquitto -m 0640 "$acl_tmp" "$ACL_PATH"
fi
rm -f -- "$acl_tmp"
acl_tmp=""

config_tmp="$(mktemp)"
cat >"$config_tmp" <<EOF_CONFIG
# Managed by scripts/install-mosquitto-broker.sh
# Password-authenticated trusted-LAN listener; TLS is not configured here.
listener ${PORT} ${BIND_ADDRESS}
protocol mqtt
allow_anonymous false
password_file ${PASSWORD_PATH}
acl_file ${ACL_PATH}
EOF_CONFIG

if [[ ! -f "$CONFIG_PATH" ]] || ! cmp -s "$config_tmp" "$CONFIG_PATH"; then
    backup_file "$CONFIG_PATH"
    install -o root -g root -m 0644 "$config_tmp" "$CONFIG_PATH"
fi
rm -f -- "$config_tmp"
config_tmp=""

systemctl enable mosquitto.service >/dev/null
if ! systemctl restart mosquitto.service; then
    echo "ERROR: Mosquitto failed to restart. Recent service log:" >&2
    journalctl -u mosquitto.service -n 80 --no-pager >&2 || true
    exit 1
fi

systemctl is-active --quiet mosquitto.service || {
    echo "ERROR: Mosquitto is not active after restart." >&2
    exit 1
}

if ! ss -ltn | awk -v suffix=":${PORT}" '$4 ~ suffix "$" { found=1 } END { exit !found }'; then
    echo "ERROR: no TCP listener was found on port ${PORT}." >&2
    exit 1
fi

test_host="$BIND_ADDRESS"
if [[ "$test_host" == "0.0.0.0" ]]; then
    test_host="127.0.0.1"
fi

if ! timeout 3 bash -c "exec 3<>/dev/tcp/${test_host}/${PORT}"; then
    echo "ERROR: the configured listener is not reachable at ${test_host}:${PORT}." >&2
    exit 1
fi

if mosquitto_pub \
    -h "$test_host" \
    -p "$PORT" \
    -t "sanlightmesh/v1/${GATEWAY_ID}/command" \
    -m '{}' \
    >/dev/null 2>&1; then
    echo "ERROR: anonymous MQTT publication unexpectedly succeeded." >&2
    exit 1
fi

broker_addresses="$(hostname -I 2>/dev/null | xargs || true)"

echo
echo "Mosquitto broker setup complete."
echo "Listener:          ${BIND_ADDRESS}:${PORT}"
echo "Host addresses:     ${broker_addresses:-not detected}"
echo "Gateway ID:         ${GATEWAY_ID}"
echo "Gateway username:   ${GATEWAY_USER}"
echo "ioBroker username:  ${IOBROKER_USER}"
echo "TLS:                disabled (trusted private LAN only)"
echo
echo "Use the gateway username/password in scripts/install-gateway.sh."
echo "Use the separate ioBroker username/password in the ioBroker MQTT adapter."
echo "Do not use localhost on the remote gateway; use this broker host's LAN IP."
