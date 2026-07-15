# Installer design

`scripts/install-gateway.sh` is the single public installation and upgrade entry
point. `scripts/setup-all.sh`, `scripts/install-service.sh` and
`scripts/install-mqtt-gateway.sh` remain lower-level internal helpers for
development and recovery.

There is no separate broker-host installer. The public installer prepares the
local Mosquitto broker on the same lamp-side Raspberry Pi.

## Responsibilities

The public installer:

1. locates and protects the private CDB and configuration directory;
2. installs BlueZ, Python, Paho MQTT, Mosquitto and MQTT client tools in one
   package phase;
3. runs offline syntax, unit and source-security checks;
4. validates the Raspberry Pi / BlueZ environment;
5. stops the project gateway and Mesh services;
6. classifies both local identities against project and BlueZ state;
7. safely reconstructs missing project token state or permits a fresh import;
8. installs and validates the persistent Mesh service;
9. attaches/imports both identities and applies local model setup;
10. creates or reuses the protected gateway configuration;
11. creates a dedicated authenticated Mosquitto listener on port `1883`;
12. creates separate gateway and ioBroker users with ACLs limited to one
    gateway ID;
13. configures the local gateway client to use `127.0.0.1`;
14. installs both persistent services and runs read-only diagnostics;
15. prints the remote ioBroker adapter settings.

Installation never calls a lamp brightness or clock write command.

## Local broker policy

The normal broker is dedicated to this SANlight gateway appliance. The installer
refuses to merge its listener/authentication policy with unrelated Mosquitto
listener or authentication fragments.

Generated private files include:

```text
/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt
/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
/etc/mosquitto/sanlight-mesh-mqtt-gateway.passwd
/etc/mosquitto/sanlight-mesh-mqtt-gateway.acl
```

The clear-text passwords remain root-only. The Mosquitto password database
contains password hashes and is readable by the `mosquitto` service group.
Passwords are passed to `mosquitto_passwd` through a pseudo-terminal, not as
command-line arguments.

The generated ACL permits:

- the local gateway user to subscribe to its command topic and publish only its
  availability, gateway, node and result trees;
- the ioBroker user to publish only the configured gateway command topic and
  subscribe only to availability, gateway, node and result output trees for
  that gateway.

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

The installer never scans for whichever identity happens to contain `appKeys`;
optional field sets may legitimately differ between the control and canonical
sender databases.

## Upgrade mode

```bash
sudo bash scripts/install-gateway.sh --reuse-existing
```

This keeps the CDB path, state directory, gateway ID, broker credentials and
refresh settings, updates `project_root`, regenerates the dedicated ACL/config
from those settings, refreshes both systemd units and runs diagnostics.

`--reuse-existing` preserves an existing generated local-broker configuration.
When it encounters a legacy external-broker TOML from an older project version,
it preserves the gateway ID, CDB path, state directory and refresh interval but
migrates the endpoint to `127.0.0.1:1883`, generates new local gateway/ioBroker
credentials, backs up the old config and tells the operator to update ioBroker.
The supported end state is always the local broker topology.

## Destructive reset

The public installer does not expose a Mesh reset. Lower-level maintenance
helpers retain explicit destructive reset switches for deliberate complete
local reinitialisation. They are not update or missing-`.state/` recovery tools.
