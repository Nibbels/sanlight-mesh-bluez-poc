# Operations and maintenance

This is the short operator guide. The complete identity, CLI and recovery material remains available in [docs/ADVANCED_REFERENCE.md](docs/ADVANCED_REFERENCE.md), but it is not required for normal operation.

## Normal service operation

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
sudo sanlight-gateway collect-diagnostics
```

- `status` shows Mosquitto, BlueZ Mesh and gateway service state.
- `doctor` performs read-only health checks and never sends a lamp write.
- `logs` shows the recent gateway journal.
- `collect-diagnostics` writes a redacted report; review it before sharing because hostnames and topology details can remain visible.

Restart only the MQTT gateway process with:

```bash
sudo sanlight-gateway restart
```

Validate the installed configuration without starting another gateway process:

```bash
sudo sanlight-gateway check-config
```

## Read-only lamp refresh

The native ioBroker adapter normally performs refreshes. For direct diagnosis, first list the installation-specific node addresses:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    list-nodes
```

Then read one lamp without changing brightness or time:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live NODE_ADDRESS
```

The legacy filename `sanlight_canonical_sender_poc.py` is a compatibility entry point for the stable `sanlight_mesh.cli` implementation. It remains intentionally unchanged until the next command set is integrated.

Detailed command syntax and the distinction between MaxBrightness and live effective output are documented in [Read-only commands](docs/ADVANCED_REFERENCE.md#read-only-commands) and [Writing commands](docs/ADVANCED_REFERENCE.md#writing-commands).

## Updating a Git checkout

Run Git as the normal repository owner, never with `sudo`:

```bash
git pull --ff-only
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh
```

The installer preserves existing keys, credentials and compatible BlueZ identity state. It updates the installed services and configuration to the current checkout.

The management helper performs Git inspection with optional locks disabled, so a root-run doctor or diagnostics command cannot refresh `.git/index` and change its ownership.

## Common recovery entry points

- Installer cannot determine the IV Index: [Missing a trusted IV Index](docs/ADVANCED_REFERENCE.md#missing-a-trusted-iv-index)
- Mesh service or D-Bus unavailable: [Troubleshooting](docs/ADVANCED_REFERENCE.md#troubleshooting)
- Canonical sender transmits but lamps do not reply: [Replay protection after a fresh SD card](docs/ADVANCED_REFERENCE.md#replay-protection-after-a-fresh-sd-card)
- Explicit sequence advancement after completed diagnosis: [Explicit local sequence recovery](docs/ADVANCED_REFERENCE.md#explicit-local-sequence-recovery)
- Full destructive rebuild boundary: [Destructive reset to a fresh sequence space](docs/ADVANCED_REFERENCE.md#destructive-reset-to-a-fresh-sequence-space)

Do not guess an IV Index, reset sequence state, copy `.state/` from another active gateway or expose Mesh keys while troubleshooting.

## Offline verification

```bash
./scripts/run-tests.sh
```

The suite compiles the Python sources, runs the offline unit tests and scans source and documentation for accidental token output. GitHub Actions runs the same gate on supported Python versions and additionally checks shell syntax and release-archive hygiene.

## Further documentation

- [SETUP.md](SETUP.md) — first installation
- [docs/ADVANCED_REFERENCE.md](docs/ADVANCED_REFERENCE.md) — complete identity, command and recovery reference
- [docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md) — broker and service operation
- [docs/MQTT_API.md](docs/MQTT_API.md) — MQTT API v1 contract
- [docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md) — hardware validation and regression plan
- [docs/RELEASES.md](docs/RELEASES.md) — release and rollback procedure
- [SECURITY.md](SECURITY.md) — security boundaries
