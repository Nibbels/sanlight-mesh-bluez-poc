#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDB="${REPO_DIR}/private/SANlightMesh.json"

# A single missing Mesh status reply is not enough to diagnose replay protection.
# Each identity therefore gets one retry, with a short pause between attempts and
# between the two short-lived D-Bus application processes.
MAX_ATTEMPTS=2
RETRY_DELAY_SECONDS=2
IDENTITY_SETTLE_SECONDS=2
SUCCESS_MARKER='GET-NET-TX COMPLETE. Node 0x'
PROBE_ATTEMPTS=0

usage() {
    cat <<'EOF_USAGE'
Usage:
  sudo bash ./scripts/diagnose-replay.sh NODE_ADDRESS [--cdb PATH]

Runs repeated read-only Config Network Transmit probes:
  1. from the control identity
  2. from the canonical sender identity

NODE_ADDRESS is a four-digit unicast value from list-nodes, for example 0002.
The command does not change lamp time, brightness, groups, or schedules.
EOF_USAGE
}

probe_output_has_status() {
    local output="$1"
    grep -Fq "$SUCCESS_MARKER" "$output"
}

run_probe_once() {
    local command="$1"
    local output="$2"

    python3 sanlight_canonical_sender_poc.py \
        --cdb "$CDB" \
        "$command" "$NODE" >"$output" 2>&1
}

run_probe_with_retries() {
    local command="$1"
    local label="$2"
    local output="$3"
    local attempt
    local attempt_output

    : >"$output"

    for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
        attempt_output="${output}.attempt-${attempt}"
        printf 'Running read-only %s probe to %s (attempt %d/%d)...\n' \
            "$label" "$NODE" "$attempt" "$MAX_ATTEMPTS"

        if ! run_probe_once "$command" "$attempt_output"; then
            printf '\n--- %s attempt %d output ---\n' "$label" "$attempt" >>"$output"
            cat "$attempt_output" >>"$output"
            echo "ERROR: ${command} failed on attempt ${attempt}:" >&2
            cat "$attempt_output" >&2
            return 2
        fi

        printf '\n--- %s attempt %d output ---\n' "$label" "$attempt" >>"$output"
        cat "$attempt_output" >>"$output"

        if probe_output_has_status "$attempt_output"; then
            PROBE_ATTEMPTS="$attempt"
            return 0
        fi

        if ((attempt < MAX_ATTEMPTS)); then
            printf 'No status reply observed; waiting %d seconds before retry.\n' \
                "$RETRY_DELAY_SECONDS"
            sleep "$RETRY_DELAY_SECONDS"
        fi
    done

    PROBE_ATTEMPTS="$MAX_ATTEMPTS"
    return 1
}

print_safe_probe_details() {
    local label="$1"
    local output="$2"

    printf '\n%s probe details (safe summary):\n' "$label"
    grep -E \
        '^(Attaching |Canonical sender attached:|Control provisioner attached:|Preparing read-only |Sending read-only |Config Network Transmit Get accepted\.|Sender Config Network Transmit Get accepted\.|Control RX DevKey:|Sender RX DevKey:|GET-NET-TX COMPLETE\.|ERROR:)' \
        "$output" | tail -n 24 || true
}

main() {
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
                [[ $# -ge 2 ]] || {
                    echo "ERROR: --cdb requires a path." >&2
                    exit 2
                }
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

    local tmp_dir
    local control_output
    local sender_output
    local control_ok=0
    local sender_ok=0
    local control_attempts=0
    local sender_attempts=0
    local result

    tmp_dir="$(mktemp -d)"
    chmod 700 "$tmp_dir"
    trap 'rm -rf "$tmp_dir"' EXIT

    control_output="${tmp_dir}/control.txt"
    sender_output="${tmp_dir}/sender.txt"

    if run_probe_with_retries get-net-tx "control" "$control_output"; then
        control_ok=1
        control_attempts="$PROBE_ATTEMPTS"
    else
        result=$?
        control_attempts="$PROBE_ATTEMPTS"
        [[ $result -ne 2 ]] || exit 2
    fi

    printf 'Waiting %d seconds before switching Mesh identity...\n' \
        "$IDENTITY_SETTLE_SECONDS"
    sleep "$IDENTITY_SETTLE_SECONDS"

    if run_probe_with_retries get-net-tx-sender "canonical-sender" "$sender_output"; then
        sender_ok=1
        sender_attempts="$PROBE_ATTEMPTS"
    else
        result=$?
        sender_attempts="$PROBE_ATTEMPTS"
        [[ $result -ne 2 ]] || exit 2
    fi

    printf '\nReplay diagnostic result\n'
    printf '========================\n'

    if [[ $control_ok -eq 1 ]]; then
        printf 'Control identity response:          YES (attempt %d/%d)\n' \
            "$control_attempts" "$MAX_ATTEMPTS"
    else
        printf 'Control identity response:          NO (after %d attempts)\n' \
            "$MAX_ATTEMPTS"
    fi

    if [[ $sender_ok -eq 1 ]]; then
        printf 'Canonical sender identity response: YES (attempt %d/%d)\n' \
            "$sender_attempts" "$MAX_ATTEMPTS"
    else
        printf 'Canonical sender identity response: NO (after %d attempts)\n' \
            "$MAX_ATTEMPTS"
    fi

    if [[ $control_ok -eq 1 && $sender_ok -eq 1 ]]; then
        cat <<'EOF_RESULT'

Result: both paths work. A sender replay-state problem is not present now.
A status reply may occasionally be missed; the retry prevents one transient loss
from being misclassified as replay protection.
EOF_RESULT
        exit 0
    fi

    if [[ $control_ok -eq 1 && $sender_ok -eq 0 ]]; then
        cat <<'EOF_RESULT'

Result: likely reused-sender replay protection state after repeated probes.
The lamp accepts the control identity but did not answer the canonical sender in
any attempt. This commonly happens after restoring the same sender address on a
fresh BlueZ state with a lower sequence number.

This remains a diagnosis, not mathematical proof: Mesh status replies can be
lost. Review the safe probe details below and read INSTRUCTIONS.md section
"Replay protection after a fresh SD card" before recovery.
EOF_RESULT
        print_safe_probe_details "Canonical sender" "$sender_output"
        printf '\nNo lamp setting was changed.\n'
        exit 0
    fi

    if [[ $control_ok -eq 0 && $sender_ok -eq 0 ]]; then
        cat <<'EOF_RESULT'

Result: this is not isolated to the canonical sender. Check lamp power, distance,
IV Index, Mesh service logs, NetKey/DeviceKey material, and controller ownership.
EOF_RESULT
        print_safe_probe_details "Control" "$control_output"
        print_safe_probe_details "Canonical sender" "$sender_output"
        exit 0
    fi

    cat <<'EOF_RESULT'

Result: unusual asymmetric state. The sender works while the control identity
does not. Inspect the safe probe details and check the control state.
EOF_RESULT
    print_safe_probe_details "Control" "$control_output"
    exit 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
