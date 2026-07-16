# Installer design

`scripts/install-gateway.sh` is the single public installation and upgrade entry
point. There is no second broker-host installer.

Lower-level scripts such as `setup-all.sh`, `install-service.sh` and
`install-mqtt-gateway.sh` remain implementation and recovery helpers. Normal
users should not assemble the installation from those scripts.

## What the installer owns

The installer prepares one self-contained SANlight gateway Pi:

1. resolves and protects the private CDB, state and configuration paths;
2. optionally reads an existing configuration in `--reuse-existing` mode;
3. installs BlueZ, Python, Paho MQTT, Mosquitto and MQTT client tools;
4. runs syntax, unit and secret-output checks;
5. validates the supported Raspberry Pi / BlueZ environment;
6. stops the project services before reconciling local identity state;
7. safely adopts existing BlueZ identities or permits a genuine fresh import;
8. installs and validates `sanlight-meshd-generic.service`;
9. attaches/imports both local identities and applies the required model setup;
10. creates or reuses gateway and ioBroker broker credentials;
11. writes the dedicated Mosquitto listener, password database and ACL;
12. validates that Mosquitto starts and anonymous access is rejected;
13. writes the gateway TOML for `127.0.0.1:1883`;
14. installs and starts `sanlight-mqtt-gateway.service`;
15. prints the ioBroker connection settings and runs read-only diagnostics.

Installation never sends lamp brightness or clock write commands.

## Normal prompts

A new installation asks only for deployment-specific values:

- gateway ID;
- read-only refresh interval.

CDB path, project state path, the CDB-derived control and canonical-sender
identities, local broker endpoint and service names are product invariants rather
than normal user choices. The SANlight app's App-ID labels must not be confused
with Bluetooth Mesh AppKey indexes; see [Detailed instructions](../INSTRUCTIONS.md#sanlight-app-id-is-not-a-bluetooth-mesh-appkey-index).

## Local broker policy

The broker is dedicated to this gateway appliance and listens on TCP port
`1883` for the trusted LAN. The gateway itself connects through
`127.0.0.1:1883`.

Generated private files include:

```text
/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt
/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
/etc/mosquitto/sanlight-mesh-mqtt-gateway.passwd
/etc/mosquitto/sanlight-mesh-mqtt-gateway.acl
/etc/mosquitto/conf.d/sanlight-mesh-mqtt-gateway.conf
```

The installer creates separate users for the local gateway and the remote
ioBroker adapter, each restricted to one exact gateway topic root. Passwords are
not passed to `mosquitto_passwd` through command-line arguments.

The installer refuses to merge its listener/authentication policy with unrelated
Mosquitto listener or authentication fragments. TLS, an external broker and a
shared central broker are custom topologies requiring separate validation.

## Identity-state matrix

Each local identity is handled independently:

| Project state | Exact CDB-derived BlueZ `node.json` | Result |
|---|---|---|
| present | present | validate identity, token and IV Index; attach |
| missing | present | validate BlueZ identity; atomically reconstruct project state; attach |
| missing | missing | permit fresh `Network1.Import` |
| present | missing | abort; automatic re-import is blocked |
| mismatch | mismatch | abort without printing private values |
| only `node.json.bak` | missing | abort for manual recovery |

Identity selection is based on the exact CDB provisioner UUID plus DeviceKey and
unicast validation. Optional BlueZ fields such as `appKeys` are never used as an
identity heuristic. Adoption reconstructs only the protected project token file
and never changes `sequenceNumber` or another BlueZ field.

## Upgrade mode

```bash
sudo bash scripts/install-gateway.sh --reuse-existing
```

This preserves:

- gateway ID;
- CDB and project-state paths;
- local broker credentials;
- refresh interval;
- BlueZ identity and sequence state.

It updates `project_root`, rebuilds the managed broker policy, refreshes both
systemd units and runs diagnostics.

A legacy external-broker configuration is migrated to the supported local-broker
topology. The installer preserves the gateway/CDB/state/refresh settings,
generates new local credentials and instructs the operator to update the
matching ioBroker adapter instance.

## Destructive reset boundary

The public installer has no `--reset-mesh-state` option. Lower-level maintenance
helpers retain explicit destructive reset functionality for deliberate complete
local reinitialisation only. It is not an update mechanism and must not be used
to recover missing `.state/` while the matching BlueZ databases still exist.

## Validated reference run

On 2026-07-16 the public installer was run on the target Raspberry Pi 3 after
`.state/` had intentionally been removed while both BlueZ identities remained.
It:

- recovered both protected project identity files;
- attached both identities without re-import or reset;
- installed local Mosquitto and generated scoped credentials/ACLs;
- started all three services;
- connected the MQTT gateway and published two node definitions;
- completed with `Doctor result: healthy`.

The target run passed 124 offline tests and the static token-output scan before
installation.
