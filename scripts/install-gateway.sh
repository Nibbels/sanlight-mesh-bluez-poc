#!/usr/bin/env bash
set -euo pipefail
umask 077

CONFIG_PATH="/etc/sanlight-mesh-mqtt-gateway/gateway.toml"
REUSE_EXISTING=0
NO_START=0

usage() {
    cat <<'EOF'
Usage: sudo bash scripts/install-gateway.sh [options]

Create or reuse a protected MQTT gateway configuration and install the
systemd service. The SANlight Mesh identities must already be prepared by
SETUP.md. This installer never changes lamp brightness or lamp time.

Options:
  --config PATH       Configuration path
                      (default: /etc/sanlight-mesh-mqtt-gateway/gateway.toml)
  --reuse-existing    Reuse and validate an existing configuration without prompts
  --no-start          Install/refresh the service without starting it
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            shift
            [[ $# -gt 0 ]] || { echo "ERROR: --config requires a path" >&2; exit 2; }
            CONFIG_PATH="$1"
            ;;
        --reuse-existing) REUSE_EXISTING=1 ;;
        --no-start) NO_START=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

[[ -f "$REPO_DIR/sanlight_mqtt_gateway.py" ]] || {
    echo "ERROR: run this installer from a complete gateway release/checkout" >&2
    exit 1
}
[[ -x /usr/bin/python3 ]] || { echo "ERROR: /usr/bin/python3 is missing" >&2; exit 1; }

if [[ "$EUID" -ne 0 ]]; then
    args=(--config "$CONFIG_PATH")
    [[ "$REUSE_EXISTING" -eq 1 ]] && args+=(--reuse-existing)
    [[ "$NO_START" -eq 1 ]] && args+=(--no-start)
    exec sudo -- bash "$0" "${args[@]}"
fi

CONFIG_PATH="$(realpath -m "$CONFIG_PATH")"
CONFIG_DIR="$(dirname "$CONFIG_PATH")"
PASSWORD_PATH="$CONFIG_DIR/mqtt-password.txt"
REPO_MARKER="$CONFIG_DIR/repository-path"

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

install -d -m 0700 "$CONFIG_DIR"

if [[ "$REUSE_EXISTING" -eq 1 ]]; then
    [[ -f "$CONFIG_PATH" ]] || {
        echo "ERROR: --reuse-existing requires $CONFIG_PATH" >&2
        exit 1
    }
else
    if [[ -f "$CONFIG_PATH" ]]; then
        echo "Existing configuration found at $CONFIG_PATH."
        if prompt_yes_no "Reuse it without changing credentials?" y; then
            REUSE_EXISTING=1
        fi
    fi
fi

if [[ "$REUSE_EXISTING" -eq 0 ]]; then
    echo
    echo "This wizard configures MQTT only. It does not provision or reset the Mesh."
    echo

    gateway_id="$(prompt "Gateway ID" "sanlight-pi")"
    [[ "$gateway_id" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || {
        echo "ERROR: gateway ID must match [a-z0-9][a-z0-9_-]{0,47}" >&2
        exit 1
    }

    cdb_path="$(prompt "Absolute path to private SANlightMesh.json")"
    cdb_path="$(realpath -e "$cdb_path")"
    [[ -f "$cdb_path" ]] || { echo "ERROR: CDB not found" >&2; exit 1; }

    state_dir="$(prompt "Absolute gateway state directory" "$REPO_DIR/.state")"
    state_dir="$(realpath -m "$state_dir")"
    [[ -f "$state_dir/canonical-sender.json" ]] || {
        echo "ERROR: canonical-sender.json is missing in $state_dir" >&2
        echo "Complete SETUP.md before installing the MQTT gateway." >&2
        exit 1
    }

    control_app_id="$(prompt "Control App-ID" "1")"
    sender_app_id="$(prompt "Canonical sender App-ID" "2")"
    [[ "$control_app_id" =~ ^[0-9]+$ && "$sender_app_id" =~ ^[0-9]+$ ]] || {
        echo "ERROR: App-IDs must be integers" >&2
        exit 1
    }

    mqtt_host="$(prompt "MQTT broker host or IP")"
    [[ -n "$mqtt_host" ]] || { echo "ERROR: broker host is required" >&2; exit 1; }
    mqtt_port="$(prompt "MQTT broker port" "1883")"
    [[ "$mqtt_port" =~ ^[0-9]+$ ]] && (( mqtt_port >= 1 && mqtt_port <= 65535 )) || {
        echo "ERROR: MQTT port must be 1..65535" >&2
        exit 1
    }

    mqtt_username="$(prompt "MQTT username")"
    [[ -n "$mqtt_username" ]] || { echo "ERROR: MQTT username is required" >&2; exit 1; }

    read -r -s -p "MQTT password: " mqtt_password
    echo
    [[ -n "$mqtt_password" ]] || { echo "ERROR: MQTT password must not be empty" >&2; exit 1; }

    mqtt_tls=false
    ca_cert=""
    if prompt_yes_no "Use MQTT TLS?" n; then
        mqtt_tls=true
        default_ca="/etc/ssl/certs/ca-certificates.crt"
        ca_cert="$(prompt "CA certificate bundle/path" "$default_ca")"
        ca_cert="$(realpath -e "$ca_cert")"
    fi

    refresh_interval="$(prompt "Read-only refresh interval in seconds (0 disables)" "1800")"
    [[ "$refresh_interval" =~ ^[0-9]+$ ]] && (( refresh_interval <= 86400 )) || {
        echo "ERROR: refresh interval must be 0..86400" >&2
        exit 1
    }

    backup_if_present "$CONFIG_PATH"
    backup_if_present "$PASSWORD_PATH"

    printf '%s' "$mqtt_password" > "$PASSWORD_PATH"
    chmod 0600 "$PASSWORD_PATH"
    unset mqtt_password

    chmod 0600 "$cdb_path"
    install -d -m 0700 "$state_dir"

    /usr/bin/python3 - \
        "$CONFIG_PATH" "$REPO_DIR" "$gateway_id" "$cdb_path" "$state_dir" \
        "$control_app_id" "$sender_app_id" "$mqtt_host" "$mqtt_port" \
        "$mqtt_username" "$PASSWORD_PATH" "$mqtt_tls" "$ca_cert" \
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
    control_app_id,
    sender_app_id,
    mqtt_host,
    mqtt_port,
    mqtt_username,
    password_path,
    mqtt_tls,
    ca_cert,
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
    f"control_app_id = {int(control_app_id)}",
    f"sender_app_id = {int(sender_app_id)}",
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
    f"tls = {'true' if mqtt_tls == 'true' else 'false'}",
]
if ca_cert:
    lines.append(f"ca_cert = {q(str(Path(ca_cert).resolve()))}")

path = Path(config_path)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
fi

chmod 0600 "$CONFIG_PATH"

# A release update may be extracted to a new directory. Keep all existing
# private paths and credentials, but atomically point project_root at the
# release from which this installer is running.
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

# Validate before installing packages or changing systemd state.
/usr/bin/python3 "$REPO_DIR/sanlight_mqtt_gateway.py" \
    --config "$CONFIG_PATH" \
    --check

install_args=(--config "$CONFIG_PATH")
[[ "$NO_START" -eq 1 ]] && install_args+=(--no-start)
bash "$REPO_DIR/scripts/install-mqtt-gateway.sh" "${install_args[@]}"

install -m 0755 "$REPO_DIR/scripts/sanlight-gateway" /usr/local/sbin/sanlight-gateway

echo
echo "Gateway installation complete."
echo "Configuration: $CONFIG_PATH"
echo "Management:    sudo sanlight-gateway doctor"

if [[ "$NO_START" -eq 0 ]]; then
    echo
    /usr/local/sbin/sanlight-gateway --config "$CONFIG_PATH" doctor || true
fi
