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
RESET_MESH_STATE=0
SKIP_PACKAGES=0
ALLOW_UNSUPPORTED=0

usage() {
    cat <<'EOF'
Usage: sudo bash scripts/install-gateway.sh [options]

Authoritative end-to-end installer for the SANlight Mesh MQTT gateway.
It installs dependencies, prepares or safely recovers the two local BlueZ
identities, creates/reuses MQTT configuration, and installs both services.
It never sends lamp brightness or lamp-clock write commands.

Options:
  --config PATH           protected gateway TOML
                          (default: /etc/sanlight-mesh-mqtt-gateway/gateway.toml)
  --cdb PATH              private SANlightMesh.json (default: private/SANlightMesh.json)
  --state-dir PATH        protected project state directory (default: .state)
  --iv-index VALUE        independently verified current Mesh IV Index
  --reuse-existing        reuse existing MQTT config without prompts
  --no-start              install MQTT service without starting it
  --skip-packages         skip apt update/install
  --allow-unsupported     warn instead of failing outside validated platform
  --reset-mesh-state      DESTRUCTIVE: clear local BlueZ/project identity state
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
        --reset-mesh-state) RESET_MESH_STATE=1 ;;
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
    [[ "$RESET_MESH_STATE" -eq 1 ]] && args+=(--reset-mesh-state)
    [[ "$SKIP_PACKAGES" -eq 1 ]] && args+=(--skip-packages)
    [[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && args+=(--allow-unsupported)
    exec sudo -- bash "$0" "${args[@]}"
fi

CONFIG_PATH="$(realpath -m "$CONFIG_PATH")"
CONFIG_DIR="$(dirname "$CONFIG_PATH")"
PASSWORD_PATH="$CONFIG_DIR/mqtt-password.txt"
REPO_MARKER="$CONFIG_DIR/repository-path"
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

# Existing configuration is authoritative for private CDB/state paths.  The
# current release path is updated later, but credentials and private paths stay.
if [[ -f "$CONFIG_PATH" ]]; then
    chmod 0600 "$CONFIG_PATH"
    if [[ "$REUSE_EXISTING" -eq 0 ]]; then
        echo "Existing configuration found at $CONFIG_PATH."
        if prompt_yes_no "Reuse it without changing broker credentials?" y; then
            REUSE_EXISTING=1
        fi
    fi
elif [[ "$REUSE_EXISTING" -eq 1 ]]; then
    echo "ERROR: --reuse-existing requires $CONFIG_PATH" >&2
    exit 1
fi

if [[ "$REUSE_EXISTING" -eq 1 ]]; then
    mapfile -t PRIVATE_PATHS < <(
        PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys
from sanlight_mesh.gateway_config import load_gateway_config
config = load_gateway_config(Path(sys.argv[1]))
print(config.cdb_path)
print(config.state_dir)
PY
    )
    [[ "${#PRIVATE_PATHS[@]}" -eq 2 ]] || {
        echo "ERROR: cannot resolve CDB/state paths from existing config" >&2
        exit 1
    }
    CDB_PATH="${PRIVATE_PATHS[0]}"
    STATE_DIR="${PRIVATE_PATHS[1]}"
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

# Gather MQTT values before the service changes. App-IDs and state paths are
# repository invariants in the normal product path and are no longer prompted.
if [[ "$REUSE_EXISTING" -eq 0 ]]; then
    echo
    echo "MQTT configuration"
    gateway_id="$(prompt "Gateway ID" "sanlight-pi")"
    [[ "$gateway_id" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || {
        echo "ERROR: gateway ID must match [a-z0-9][a-z0-9_-]{0,47}" >&2
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
        ca_cert="$(prompt "CA certificate bundle/path" "/etc/ssl/certs/ca-certificates.crt")"
        ca_cert="$(realpath -e "$ca_cert")"
    fi
    refresh_interval="$(prompt "Read-only refresh interval in seconds (0 disables)" "1800")"
    [[ "$refresh_interval" =~ ^[0-9]+$ ]] && (( refresh_interval <= 86400 )) || {
        echo "ERROR: refresh interval must be 0..86400" >&2
        exit 1
    }
fi

SETUP_ARGS=(--cdb "$CDB_PATH" --state-dir "$STATE_DIR")
[[ -n "$IV_INDEX" ]] && SETUP_ARGS+=(--iv-index "$IV_INDEX")
[[ "$RESET_MESH_STATE" -eq 1 ]] && SETUP_ARGS+=(--reset-mesh-state)
[[ "$SKIP_PACKAGES" -eq 1 ]] && SETUP_ARGS+=(--skip-packages)
[[ "$ALLOW_UNSUPPORTED" -eq 1 ]] && SETUP_ARGS+=(--allow-unsupported)

echo
echo "Preparing or safely adopting local Mesh identities..."
bash "$REPO_DIR/scripts/setup-all.sh" "${SETUP_ARGS[@]}"

# setup-all.sh preserves a gateway that was already active when invoked directly.
# Keep it stopped while this authoritative installer updates protected config and
# the unit, then let install-mqtt-gateway.sh perform the single final restart.
systemctl stop sanlight-mqtt-gateway.service 2>/dev/null || true

if [[ "$REUSE_EXISTING" -eq 0 ]]; then
    backup_if_present "$CONFIG_PATH"
    backup_if_present "$PASSWORD_PATH"
    printf '%s' "$mqtt_password" > "$PASSWORD_PATH"
    chmod 0600 "$PASSWORD_PATH"
    unset mqtt_password

    /usr/bin/python3 - \
        "$CONFIG_PATH" "$REPO_DIR" "$gateway_id" "$CDB_PATH" "$STATE_DIR" \
        "$mqtt_host" "$mqtt_port" "$mqtt_username" "$PASSWORD_PATH" \
        "$mqtt_tls" "$ca_cert" "$refresh_interval" <<'PY'
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
echo "Management: sudo sanlight-gateway doctor"
if [[ "$NO_START" -eq 0 ]]; then
    echo
    /usr/local/sbin/sanlight-gateway --config "$CONFIG_PATH" doctor || true
fi
