# Installer design

`scripts/install-gateway.sh` is the single public installation and upgrade entry point. `scripts/setup-all.sh`, `scripts/install-service.sh` and `scripts/install-mqtt-gateway.sh` remain lower-level helpers for development and recovery.

## Responsibilities

The public installer:

1. validates the private CDB without printing secrets;
2. installs Mesh and MQTT dependencies in one package phase;
3. runs offline syntax, unit and source-security checks;
4. validates the Raspberry Pi / BlueZ environment;
5. stops the project gateway and Mesh services;
6. classifies both local identities against project and BlueZ state;
7. safely reconstructs missing project token state or permits a fresh import;
8. installs and validates the persistent Mesh service;
9. attaches/imports the two identities and applies local model setup;
10. creates or reuses protected MQTT configuration;
11. installs the MQTT service and runs read-only diagnostics.

Installation never calls a lamp brightness or clock write command.

## Identity-state matrix

Each identity is handled independently:

| Project state | Exact CDB-derived BlueZ `node.json` | Result |
|---|---|---|
| present | present | validate identity, token and IV Index; attach |
| missing | present | validate BlueZ identity; atomically reconstruct project state; attach |
| missing | missing | permit fresh `Network1.Import` |
| present | missing | abort; automatic re-import is blocked |
| any mismatch | any mismatch | abort without printing private values |
| `node.json.bak` only | missing | abort for manual recovery |

The BlueZ database path is `/var/lib/bluetooth/mesh/<provisioner-uuid-without-hyphens>/node.json`. The installer never scans for whichever identity happens to contain `appKeys`; optional field sets may legitimately differ between the control and canonical-sender databases.

## Validation before adoption

Recovery requires all of the following:

- exact provisioner UUID-derived path;
- regular, non-symlink, root-owned private `node.json`;
- DeviceKey equality with the private CDB;
- exact CDB unicast address;
- valid 64-bit token representation;
- valid 32-bit IV Index;
- agreement with any existing project/CDB/explicit IV Index source.

Only the normal protected token-state JSON is reconstructed. `sequenceNumber`, NetKey/AppKey data and all other BlueZ fields remain untouched.

## Upgrade mode

```bash
sudo bash scripts/install-gateway.sh --reuse-existing
```

This keeps the CDB path, state directory, broker credentials and gateway settings, updates `project_root` to the current checkout, refreshes both systemd units and runs diagnostics.

## Destructive reset

`--reset-mesh-state` deliberately removes local BlueZ and project token state after validation. It is not an update mechanism and does not reset lamps. Reusing the same sender address after deleting sequence state can trigger Bluetooth Mesh replay protection; review the recovery section in `INSTRUCTIONS.md` first.
