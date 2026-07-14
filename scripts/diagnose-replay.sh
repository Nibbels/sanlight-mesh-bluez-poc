#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDB="${REPO_DIR}/private/SANlightMesh.json"

usage() {
    cat <<'EOF'
Usage:
  sudo bash ./scripts/diagnose-replay.sh NODE_ADDRESS [--cdb PATH]

Runs two read-only Config Network Transmit probes:
  1. from the control identity
  2. from the canonical sender identity

NODE_ADDRESS is a four-digit unicast value from list-nodes, for example 0002.
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi

if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: run this diagnostic via sudo." >&2
    exit 2
fi

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 2
fi

NODE="$1"
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cdb)
            [[ $# -ge 2 ]] || { echo "ERROR: --cdb requires a path." >&2; exit 2; }
            CDB="$2"
            shift 2
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
done

cd "$REPO_DIR"
TMP_DIR="$(mktemp -d)"
chmod 700 "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

run_probe() {
    local command="$1"
    local output="$2"
    if ! python3 sanlight_canonical_sender_poc.py \
        --cdb "$CDB" \
        "$command" "$NODE" >"$output" 2>&1
    then
        echo "ERROR: ${command} failed:" >&2
        cat "$output" >&2
        return 2
    fi
}

CONTROL_OUTPUT="${TMP_DIR}/control.txt"
SENDER_OUTPUT="${TMP_DIR}/sender.txt"

printf 'Running read-only control probe to %s...\n' "$NODE"
run_probe get-net-tx "$CONTROL_OUTPUT"
printf 'Running read-only canonical-sender probe to %s...\n' "$NODE"
run_probe get-net-tx-sender "$SENDER_OUTPUT"

CONTROL_OK=0
SENDER_OK=0
grep -q 'GET-NET-TX COMPLETE. Node 0x' "$CONTROL_OUTPUT" && CONTROL_OK=1
grep -q 'GET-NET-TX COMPLETE. Node 0x' "$SENDER_OUTPUT" && SENDER_OK=1

printf '\nReplay diagnostic result\n'
printf '========================\n'
printf 'Control identity response:          %s\n' "$([[ $CONTROL_OK -eq 1 ]] && echo YES || echo NO)"
printf 'Canonical sender identity response: %s\n' "$([[ $SENDER_OK -eq 1 ]] && echo YES || echo NO)"

if [[ $CONTROL_OK -eq 1 && $SENDER_OK -eq 1 ]]; then
    cat <<'EOF'

Result: both paths work. A sender replay-state problem is not present now.
EOF
    exit 0
fi

if [[ $CONTROL_OK -eq 1 && $SENDER_OK -eq 0 ]]; then
    cat <<'EOF'

Result: likely reused-sender replay protection state.
The lamp accepts the control identity but rejects the canonical sender identity.
This commonly happens after restoring the same sender address on a fresh BlueZ
state with a lower sequence number.

No lamp setting was changed. Read INSTRUCTIONS.md section
"Replay protection after a fresh SD card" before recovery.
EOF
    exit 0
fi

if [[ $CONTROL_OK -eq 0 && $SENDER_OK -eq 0 ]]; then
    cat <<'EOF'

Result: this is not isolated to the canonical sender. Check lamp power, distance,
IV Index, Mesh service logs, NetKey/DeviceKey material, and controller ownership.
EOF
    exit 0
fi

cat <<'EOF'

Result: unusual asymmetric state. The sender works while the control identity
does not. Inspect both full probe commands manually and check the control state.
EOF
exit 0
