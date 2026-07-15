#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

CONFIG_PATH="/etc/sanlight-mesh-mqtt-gateway/gateway.toml"
CDB_PATH="$REPO_DIR/private/SANlightMesh.json"
STATE_DIR="$REPO_DIR/.state"
IV_INDEX=""
REUSE_EXISTING=0
NO_START=0
SKIP_PACKAGES=0
ALLOW_UNSUPPORTED=0
WRITE_CONFIG=0
REGENERATE_CREDENTIALS=0
MIGRATED_EXTERNAL_BROKER=0

usage() {
    cat <<'EOF'
Usage: sudo bash scripts/install-gateway.sh [options]

Authoritative end-to-end installer for the SANlight Mesh MQTT gateway.
It installs BlueZ Mesh, a local authenticated Mosquitto broker, the SANlight
MQTT gateway, and both systemd services on the lamp-side Raspberry Pi.
It never sends lamp brightness or lamp-clock write commands.

Options:
  --config PATH           protected gateway TOML
                          (default: /etc/sanlight-mesh-mqtt-gateway/gateway.toml)
  --cdb PATH              private SANlightMesh.json (default: private/SANlightMesh.json)
  --state-dir PATH        protected project state directory (default: .state)
  --iv-index VALUE        independently verified current Mesh IV Index
  --reuse-existing        reuse local settings/credentials; migrate legacy external config
  --no-start              install the gateway service without starting it
  --skip-packages         skip apt update/install
  --allow-unsupported     warn instead of failing outside validated platform
  -h, --help              show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            [[ $# -ge 2 ]] || { echo "ERROR: --config requires a path" >&2; exit 2; }
            CONFIG_PATH="$2"; shift
            ;;
        --cdb)
            [[ $# -ge 2 ]] || { echo "ERROR: --cdb requires a path" >&2; exit 2; }
            CDB_PATH="$2"; shift
            ;;
        --state-dir)
            [[ $# -ge 2 ]] || { echo "ERROR: --state-dir requires a path" >&2; exit 2; }
            STATE_DIR="$2"; shift
            ;;
        --iv-index)
            [[ $# -ge 2 ]] || { echo "ERROR: --iv-index requires a value" >&2; exit 2; }
            IV_INDEX="$2"; shift
            ;;
        --reuse-existing) REUSE_EXISTING=1 ;;
        --no-start) NO_START=1 ;;
        --skip-packages) SKIP_PACKAGES=1 ;;
        --allow-unsupported) ALLOW_UNSUPPORTED=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ -f "$REPO_DIR/sanlight_mqtt_gateway.py" ]] || {
    echo "ERROR: run this installer from a complete gateway release/checkout" >&2
    exit 1
}
[[ -x /usr/bin/python3 ]] || { echo "ERROR: /usr/bin/python3 is missing" >&2; exit 1; }

if [[ "$EUID" -ne 0 ]]; then
    args=(--config "$CONFIG_PATH" --cdb "$CDB_PATH" --state-dir "$STATE_DIR")
    [[ -n "$IV_INDEX" ]] && args+=(--iv-index "$IV_INDEX")
    [[ "$REUSE_EXISTING" -eq 1 ]] && args+=(--reuse-existing)
    [[ "$NO_START" -eq 1 ]] && args+=(--no-start)
    [[ "$SKIP_PACKAGES" -eq 1 ]] && args+=(--skip-packages)
    [[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && args+=(--allow-unsupported)
    exec sudo -- bash "$0" "${args[@]}"
fi

CONFIG_PATH="$(realpath -m "$CONFIG_PATH")"
CONFIG_DIR="$(dirname "$CONFIG_PATH")"
PASSWORD_PATH="$CONFIG_DIR/mqtt-password.txt"
IOBROKER_PASSWORD_PATH="$CONFIG_DIR/iobroker-mqtt-password.txt"
REPO_MARKER="$CONFIG_DIR/repository-path"

MOSQUITTO_CONFIG="/etc/mosquitto/conf.d/sanlight-mesh-mqtt-gateway.conf"
MOSQUITTO_PASSWORD_DB="/etc/mosquitto/sanlight-mesh-mqtt-gateway.passwd"
MOSQUITTO_ACL="/etc/mosquitto/sanlight-mesh-mqtt-gateway.acl"
MOSQUITTO_PORT=1883

install -d -m 0700 "$CONFIG_DIR"

prompt() {
    local label="$1" default="${2-}" value
    if [[ -n "$default" ]]; then
        read -r -p "$label [$default]: " value
        printf '%s' "${value:-$default}"
    else
        read -r -p "$label: " value
        printf '%s' "$value"
    fi
}

prompt_yes_no() {
    local label="$1" default="${2:-n}" value
    while true; do
        read -r -p "$label [${default^^}/$([[ "$default" == y ]] && echo n || echo y)]: " value
        value="${value:-$default}"
        case "${value,,}" in
            y|yes) return 0 ;;
            n|no) return 1 ;;
            *) echo "Please answer yes or no." ;;
        esac
    done
}

backup_if_present() {
    local path="$1"
    if [[ -e "$path" ]]; then
        local stamp backup
        stamp="$(date --utc +%Y%m%dT%H%M%SZ)"
        backup="${path}.backup-${stamp}"
        cp -a -- "$path" "$backup"
        echo "Backed up $path to $backup"
    fi
}

generate_secret_file() {
    local path="$1"
    /usr/bin/python3 - "$path" <<'PY'
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1])
path.write_text(secrets.token_urlsafe(36) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
}

# Existing configuration is authoritative for private CDB/state paths and
# local broker credentials. The product installer intentionally supports only
# the self-contained gateway-Pi broker topology.
if [[ -f "$CONFIG_PATH" ]]; then
    chmod 0600 "$CONFIG_PATH"
    if [[ "$REUSE_EXISTING" -eq 0 ]]; then
        echo "Existing configuration found at $CONFIG_PATH."
        if prompt_yes_no "Reuse existing installation settings (legacy external broker configs are migrated locally)?" y; then
            REUSE_EXISTING=1
        fi
    fi
elif [[ "$REUSE_EXISTING" -eq 1 ]]; then
    echo "ERROR: --reuse-existing requires $CONFIG_PATH" >&2
    exit 1
fi

if [[ "$REUSE_EXISTING" -eq 1 ]]; then
    mapfile -t EXISTING_VALUES < <(
        PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys
from sanlight_mesh.gateway_config import load_gateway_config

config = load_gateway_config(Path(sys.argv[1]))
print(config.cdb_path)
print(config.state_dir)
print(config.gateway_id)
print(config.mqtt.host)
print(config.mqtt.port)
print(config.mqtt.username or "")
print(config.mqtt.password_file or "")
print(config.refresh_interval_seconds)
print("true" if config.mqtt.tls else "false")
PY
    )
    [[ "${#EXISTING_VALUES[@]}" -eq 9 ]] || {
        echo "ERROR: cannot resolve settings from existing gateway config" >&2
        exit 1
    }
    CDB_PATH="${EXISTING_VALUES[0]}"
    STATE_DIR="${EXISTING_VALUES[1]}"
    gateway_id="${EXISTING_VALUES[2]}"
    mqtt_host="${EXISTING_VALUES[3]}"
    mqtt_port="${EXISTING_VALUES[4]}"
    mqtt_username="${EXISTING_VALUES[5]}"
    PASSWORD_PATH="${EXISTING_VALUES[6]}"
    refresh_interval="${EXISTING_VALUES[7]}"
    mqtt_tls="${EXISTING_VALUES[8]}"
    case "${mqtt_host,,}:${mqtt_port}:${mqtt_tls}" in
        localhost:${MOSQUITTO_PORT}:false|127.0.0.1:${MOSQUITTO_PORT}:false|::1:${MOSQUITTO_PORT}:false)
            ;;
        *)
            echo "Migrating the existing gateway configuration to the supported local broker topology."
            echo "The gateway ID, CDB path, state directory and refresh interval will be preserved."
            echo "New gateway/ioBroker MQTT credentials will be generated; update the ioBroker adapter afterward."
            mqtt_host="127.0.0.1"
            mqtt_port="$MOSQUITTO_PORT"
            mqtt_username="sanlight-gateway-${gateway_id}"
            PASSWORD_PATH="$CONFIG_DIR/mqtt-password.txt"
            WRITE_CONFIG=1
            REGENERATE_CREDENTIALS=1
            MIGRATED_EXTERNAL_BROKER=1
            ;;
    esac
else
    echo
    echo "Gateway configuration"
    gateway_id="$(prompt "Gateway ID" "sanlight-pi")"
    [[ "$gateway_id" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || {
        echo "ERROR: gateway ID must match [a-z0-9][a-z0-9_-]{0,47}" >&2
        exit 1
    }
    refresh_interval="$(prompt "Read-only refresh interval in seconds (0 disables)" "1800")"
    [[ "$refresh_interval" =~ ^[0-9]+$ ]] && (( refresh_interval <= 86400 )) || {
        echo "ERROR: refresh interval must be 0..86400" >&2
        exit 1
    }
    mqtt_host="127.0.0.1"
    mqtt_port="$MOSQUITTO_PORT"
    mqtt_username="sanlight-gateway-${gateway_id}"
    WRITE_CONFIG=1
    REGENERATE_CREDENTIALS=1
fi

CDB_PATH="$(realpath -m "$CDB_PATH")"
STATE_DIR="$(realpath -m "$STATE_DIR")"
[[ -f "$CDB_PATH" ]] || {
    echo "ERROR: private SANlight CDB not found: $CDB_PATH" >&2
    echo "Copy the export to private/SANlightMesh.json or pass --cdb PATH." >&2
    exit 1
}
if [[ "$CDB_PATH" == "$REPO_DIR/private/"* ]]; then
    install -d -m 0700 "$REPO_DIR/private"
fi
install -d -m 0700 "$STATE_DIR"
chmod 0600 "$CDB_PATH"

if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
    echo
    echo "Installing validated Mesh, MQTT client and local broker packages..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        bluez bluez-meshd dbus git iproute2 mosquitto mosquitto-clients procps \
        python3 python3-dbus python3-gi python3-paho-mqtt rfkill
fi

for command in mosquitto mosquitto_passwd mosquitto_pub mosquitto_sub ss; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "ERROR: required local broker command is missing: $command" >&2
        echo "Run without --skip-packages or install the documented package set first." >&2
        exit 1
    }
done

if ! /usr/bin/python3 -c 'import paho.mqtt.client' >/dev/null 2>&1; then
    echo "ERROR: Python package paho.mqtt is unavailable." >&2
    echo "Run without --skip-packages or install python3-paho-mqtt." >&2
    exit 1
fi

SETUP_ARGS=(--cdb "$CDB_PATH" --state-dir "$STATE_DIR" --skip-packages)
[[ -n "$IV_INDEX" ]] && SETUP_ARGS+=(--iv-index "$IV_INDEX")
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && SETUP_ARGS+=(--allow-unsupported)

echo
echo "Preparing or safely adopting local Mesh identities..."
bash "$REPO_DIR/scripts/setup-all.sh" "${SETUP_ARGS[@]}"

# setup-all.sh preserves a previously running gateway when used directly. Keep
# it stopped while broker credentials, configuration and the unit are updated.
systemctl stop sanlight-mqtt-gateway.service 2>/dev/null || true

echo
echo "Configuring the local authenticated Mosquitto broker..."

[[ -f /etc/mosquitto/mosquitto.conf ]] || {
    echo "ERROR: /etc/mosquitto/mosquitto.conf is missing" >&2
    exit 1
}
grep -Eq '^[[:space:]]*include_dir[[:space:]]+/etc/mosquitto/conf\.d[[:space:]]*$' \
    /etc/mosquitto/mosquitto.conf || {
    echo "ERROR: Mosquitto does not include /etc/mosquitto/conf.d" >&2
    echo "Refusing to rewrite an unfamiliar broker configuration." >&2
    exit 1
}
install -d -m 0755 /etc/mosquitto/conf.d

if grep -RqsE '^[[:space:]]*persistence[[:space:]]+false[[:space:]]*$' \
    /etc/mosquitto/mosquitto.conf /etc/mosquitto/conf.d; then
    echo "ERROR: Mosquitto persistence is explicitly disabled." >&2
    echo "Retained gateway state must survive broker restarts." >&2
    exit 1
fi
if ! grep -RqsE '^[[:space:]]*persistence[[:space:]]+true[[:space:]]*$' \
    /etc/mosquitto/mosquitto.conf /etc/mosquitto/conf.d; then
    echo "ERROR: the Debian Mosquitto configuration does not enable persistence." >&2
    echo "Refusing to guess global persistence settings in an unfamiliar configuration." >&2
    exit 1
fi

shopt -s nullglob
conflicting=()
for fragment in /etc/mosquitto/conf.d/*.conf; do
    [[ "$fragment" == "$MOSQUITTO_CONFIG" ]] && continue
    if grep -Eq '^[[:space:]]*(listener|port|password_file|acl_file|plugin|allow_anonymous|per_listener_settings)[[:space:]]+' "$fragment"; then
        conflicting+=("$fragment")
    fi
done
shopt -u nullglob
if [[ "${#conflicting[@]}" -gt 0 ]]; then
    echo "ERROR: another Mosquitto listener/authentication configuration exists:" >&2
    printf '  %s\n' "${conflicting[@]}" >&2
    echo "This installer manages a dedicated local SANlight broker and will not merge unrelated broker policy." >&2
    exit 1
fi

gateway_mqtt_user="$mqtt_username"
iobroker_mqtt_user="sanlight-iobroker-${gateway_id}"
[[ -n "$gateway_mqtt_user" ]] || {
    echo "ERROR: local broker configuration requires an MQTT username" >&2
    exit 1
}
[[ -n "$PASSWORD_PATH" ]] || {
    echo "ERROR: local broker configuration requires an MQTT password file" >&2
    exit 1
}

if [[ "$REGENERATE_CREDENTIALS" -eq 1 ]]; then
    backup_if_present "$CONFIG_PATH"
    backup_if_present "$PASSWORD_PATH"
    backup_if_present "$IOBROKER_PASSWORD_PATH"
    generate_secret_file "$PASSWORD_PATH"
    generate_secret_file "$IOBROKER_PASSWORD_PATH"
else
    [[ -f "$PASSWORD_PATH" ]] || {
        echo "ERROR: existing gateway MQTT password file is missing: $PASSWORD_PATH" >&2
        exit 1
    }
    chmod 0600 "$PASSWORD_PATH"
    if [[ ! -f "$IOBROKER_PASSWORD_PATH" ]]; then
        echo "The ioBroker MQTT password file is missing; generating a replacement."
        echo "Update the ioBroker adapter with the new password after installation."
        generate_secret_file "$IOBROKER_PASSWORD_PATH"
    fi
fi

BROKER_STAGE="$(mktemp -d /etc/mosquitto/.sanlight-gateway-install.XXXXXX)"
STAGED_PASSWORD_DB="$BROKER_STAGE/passwords"
STAGED_ACL="$BROKER_STAGE/acl"
STAGED_CONFIG="$BROKER_STAGE/config"
cleanup_broker_stage() {
    rm -rf -- "$BROKER_STAGE"
}
trap cleanup_broker_stage EXIT

/usr/bin/python3 "$REPO_DIR/scripts/mosquitto-password.py" \
    --password-db "$STAGED_PASSWORD_DB" \
    --username "$gateway_mqtt_user" \
    --secret-file "$PASSWORD_PATH" \
    --create
/usr/bin/python3 "$REPO_DIR/scripts/mosquitto-password.py" \
    --password-db "$STAGED_PASSWORD_DB" \
    --username "$iobroker_mqtt_user" \
    --secret-file "$IOBROKER_PASSWORD_PATH"

cat > "$STAGED_ACL" <<EOF
# Managed by scripts/install-gateway.sh for gateway ${gateway_id}.
user ${gateway_mqtt_user}
topic read sanlightmesh/v1/${gateway_id}/command
topic write sanlightmesh/v1/${gateway_id}/availability
topic write sanlightmesh/v1/${gateway_id}/gateway/#
topic write sanlightmesh/v1/${gateway_id}/nodes/#
topic write sanlightmesh/v1/${gateway_id}/result/#

user ${iobroker_mqtt_user}
topic write sanlightmesh/v1/${gateway_id}/command
topic read sanlightmesh/v1/${gateway_id}/availability
topic read sanlightmesh/v1/${gateway_id}/gateway/#
topic read sanlightmesh/v1/${gateway_id}/nodes/#
topic read sanlightmesh/v1/${gateway_id}/result/#
EOF

cat > "$STAGED_CONFIG" <<EOF
# Managed by scripts/install-gateway.sh.
# Plain MQTT is intended only for a trusted private LAN.
listener ${MOSQUITTO_PORT}
protocol mqtt
socket_domain ipv4
allow_anonymous false
password_file ${MOSQUITTO_PASSWORD_DB}
acl_file ${MOSQUITTO_ACL}
EOF

chown root:mosquitto "$STAGED_PASSWORD_DB" "$STAGED_ACL"
chmod 0640 "$STAGED_PASSWORD_DB" "$STAGED_ACL"
chown root:root "$STAGED_CONFIG"
chmod 0644 "$STAGED_CONFIG"
chmod 0600 "$PASSWORD_PATH" "$IOBROKER_PASSWORD_PATH"

for item in password-db acl config; do
    case "$item" in
        password-db) target="$MOSQUITTO_PASSWORD_DB" ;;
        acl) target="$MOSQUITTO_ACL" ;;
        config) target="$MOSQUITTO_CONFIG" ;;
    esac
    if [[ -e "$target" ]]; then
        cp -a -- "$target" "$BROKER_STAGE/original-$item"
        : > "$BROKER_STAGE/had-$item"
    fi
done

restore_previous_broker_files() {
    local item target
    for item in password-db acl config; do
        case "$item" in
            password-db) target="$MOSQUITTO_PASSWORD_DB" ;;
            acl) target="$MOSQUITTO_ACL" ;;
            config) target="$MOSQUITTO_CONFIG" ;;
        esac
        if [[ -e "$BROKER_STAGE/had-$item" ]]; then
            cp -a -- "$BROKER_STAGE/original-$item" "$target"
        else
            rm -f -- "$target"
        fi
    done
}

fail_and_restore_broker() {
    local message="$1"
    echo "ERROR: $message; restoring previous broker files." >&2
    restore_previous_broker_files
    systemctl restart mosquitto.service 2>/dev/null || true
    exit 1
}

if ! mv -f -- "$STAGED_PASSWORD_DB" "$MOSQUITTO_PASSWORD_DB" \
    || ! mv -f -- "$STAGED_ACL" "$MOSQUITTO_ACL" \
    || ! mv -f -- "$STAGED_CONFIG" "$MOSQUITTO_CONFIG"; then
    fail_and_restore_broker "could not install the generated broker files"
fi

if ! systemctl enable mosquitto.service; then
    fail_and_restore_broker "could not enable mosquitto.service"
fi
if ! systemctl restart mosquitto.service; then
    journalctl --no-pager -u mosquitto.service -n 100 >&2 || true
    fail_and_restore_broker "Mosquitto rejected the generated configuration"
fi
systemctl is-active --quiet mosquitto.service ||     fail_and_restore_broker "Mosquitto is not active after restart"

for _ in $(seq 1 20); do
    if ss -ltn | grep -Eq "[.:]${MOSQUITTO_PORT}[[:space:]]"; then
        break
    fi
    sleep 0.25
done
ss -ltn | grep -Eq "[.:]${MOSQUITTO_PORT}[[:space:]]" ||     fail_and_restore_broker "Mosquitto is not listening on TCP port ${MOSQUITTO_PORT}"

if mosquitto_pub -V mqttv5 -h 127.0.0.1 -p "$MOSQUITTO_PORT" \
    -t "sanlightmesh/v1/${gateway_id}/command" -m '{}' \
    >/dev/null 2>&1; then
    fail_and_restore_broker "anonymous MQTT publication was unexpectedly accepted"
fi

trap - EXIT
cleanup_broker_stage

if [[ "$WRITE_CONFIG" -eq 1 ]]; then
    /usr/bin/python3 - \
        "$CONFIG_PATH" "$REPO_DIR" "$gateway_id" "$CDB_PATH" "$STATE_DIR" \
        "$mqtt_host" "$mqtt_port" "$mqtt_username" "$PASSWORD_PATH" \
        "$refresh_interval" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

(
    config_path,
    repo_dir,
    gateway_id,
    cdb_path,
    state_dir,
    mqtt_host,
    mqtt_port,
    mqtt_username,
    password_path,
    refresh_interval,
) = sys.argv[1:]

q = json.dumps
lines = [
    "# Generated by scripts/install-gateway.sh",
    "# Never commit this file or the referenced password/CDB files.",
    "",
    "[gateway]",
    f"id = {q(gateway_id)}",
    f"project_root = {q(str(Path(repo_dir).resolve()))}",
    f"cdb = {q(str(Path(cdb_path).resolve()))}",
    f"state_dir = {q(str(Path(state_dir).resolve()))}",
    "control_app_id = 1",
    "sender_app_id = 2",
    "command_timeout_seconds = 45",
    "queue_max_size = 32",
    "dedup_ttl_seconds = 86400",
    "dedup_max_entries = 512",
    "coalesce_window_seconds = 2.0",
    "state_fresh_seconds = 0",
    "refresh_on_start = true",
    f"refresh_interval_seconds = {int(refresh_interval)}",
    "",
    "[mqtt]",
    f"host = {q(mqtt_host)}",
    f"port = {int(mqtt_port)}",
    'topic_prefix = "sanlightmesh/v1"',
    f"client_id = {q('sanlightmesh-' + gateway_id)}",
    "keepalive_seconds = 60",
    "qos = 1",
    f"username = {q(mqtt_username)}",
    f"password_file = {q(str(Path(password_path).resolve()))}",
    "tls = false",
]
path = Path(config_path)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
fi

chmod 0600 "$CONFIG_PATH"

# Release updates may move the checkout. Preserve private paths/credentials but
# point project_root at the release running this installer.
/usr/bin/python3 - "$CONFIG_PATH" "$REPO_DIR" <<'PY'
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

path = Path(sys.argv[1])
repo = str(Path(sys.argv[2]).resolve())
text = path.read_text(encoding="utf-8")
data = tomllib.loads(text)
if not isinstance(data.get("gateway"), dict):
    raise SystemExit("gateway configuration has no [gateway] table")

lines = text.splitlines()
section_start = None
section_end = len(lines)
for index, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "[gateway]":
        section_start = index
        continue
    if section_start is not None and stripped.startswith("[") and stripped.endswith("]"):
        section_end = index
        break
if section_start is None:
    raise SystemExit("gateway configuration has no [gateway] table")

replacement = f"project_root = {json.dumps(repo)}"
pattern = re.compile(r"^\s*project_root\s*=")
for index in range(section_start + 1, section_end):
    if pattern.match(lines[index]):
        lines[index] = replacement
        break
else:
    lines.insert(section_start + 1, replacement)

temporary = path.with_name(path.name + ".tmp")
temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY

printf '%s\n' "$REPO_DIR" > "$REPO_MARKER"
chmod 0644 "$REPO_MARKER"

/usr/bin/python3 "$REPO_DIR/sanlight_mqtt_gateway.py" \
    --config "$CONFIG_PATH" \
    --check

INSTALL_ARGS=(--config "$CONFIG_PATH" --skip-packages)
[[ "$NO_START" -eq 1 ]] && INSTALL_ARGS+=(--no-start)
bash "$REPO_DIR/scripts/install-mqtt-gateway.sh" "${INSTALL_ARGS[@]}"

install -m 0755 "$REPO_DIR/scripts/sanlight-gateway" /usr/local/sbin/sanlight-gateway

echo
echo "Gateway installation complete."
echo "Configuration: $CONFIG_PATH"
echo "Local MQTT broker: 127.0.0.1:${mqtt_port}"
echo "Management: sudo sanlight-gateway doctor"

echo
echo "ioBroker MQTT client settings:"
echo "  Broker host: one stable LAN IP/hostname of this SANlight gateway Pi"
echo "  Broker port: ${MOSQUITTO_PORT}"
echo "  Username: ${iobroker_mqtt_user}"
echo "  Password: sudo cat ${IOBROKER_PASSWORD_PATH}"
echo "  Gateway ID: ${gateway_id}"
echo "  Topic root: sanlightmesh/v1/${gateway_id}"
if [[ "$MIGRATED_EXTERNAL_BROKER" -eq 1 ]]; then
    echo "  IMPORTANT: replace the previous ioBroker broker/credentials with these local-gateway settings."
fi
echo
echo "Detected LAN addresses:"
hostname -I 2>/dev/null | tr ' ' '\n' | sed '/^$/d; s/^/  /' || true
echo "Use a stable DHCP reservation or hostname for the ioBroker connection."

if [[ "$NO_START" -eq 0 ]]; then
    echo
    /usr/local/sbin/sanlight-gateway --config "$CONFIG_PATH" doctor || true
fi
