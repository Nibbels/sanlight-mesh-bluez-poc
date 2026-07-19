# Security policy

## Supported status

This is a pre-1.0 community project. Security fixes target the current `main`
branch and the most recent tagged release once releases are published.

## Secret boundary

The gateway host is the only component that may possess:

- the private SANlight CDB;
- NetKeys, AppKeys and DeviceKeys;
- BlueZ local identity tokens;
- sender sequence state;
- the local gateway MQTT password;
- the ioBroker MQTT password generated for its local broker.

The ioBroker adapter receives only its scoped MQTT username/password and the
configured gateway ID. It must never receive Mesh keys or BlueZ state.

## MQTT broker

The normal installer runs Mosquitto on the gateway Pi with:

- anonymous access disabled;
- random separate gateway and ioBroker credentials;
- ACLs restricted to one exact gateway topic root;
- no internet exposure;
- retained broker persistence supplied by the validated Debian configuration.

Plain MQTT credentials are acceptable only on a trusted isolated LAN/VLAN. Use
TLS when traffic crosses an untrusted segment; TLS deployment is an advanced
custom topology and is not silently enabled by the default installer.

One ioBroker adapter instance must be restricted to one gateway ID and one
broker connection. Separate rooms or facilities should use separate gateway
Pis, IDs, credentials and adapter instances.

## Password handling

Clear-text password files are mode `0600` and root-owned. The installer passes
passwords to `mosquitto_passwd` through a pseudo-terminal so they are not placed
in process command-line arguments. The resulting hashed Mosquitto password
database is readable only by root and the `mosquitto` service group.

Do not publish or include these files in diagnostics:

```text
/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt
/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
/etc/mosquitto/sanlight-mesh-mqtt-gateway.passwd
```

## Local files

- config, CDB and clear-text MQTT password files: mode `0600`;
- state directories: mode `0700`;
- do not commit runtime-private material;
- do not restore an older sender sequence state over a newer one;
- do not clone one active sender identity onto multiple running gateways.

## Diagnostics

Use:

```bash
sudo sanlight-gateway collect-diagnostics
```

Review the resulting text before sharing. Do not attach the CDB, password files,
private keys, `/var/lib/bluetooth/mesh`, or `.state/` files.

## Service identity

The currently validated pre-1.0 gateway unit runs as `root` because the existing
BlueZ Mesh D-Bus and private-state layout were validated with root ownership.
The unit still applies `NoNewPrivileges`, restricted address families, a private
temporary directory, read-only application/config paths and an explicit
writable state path.

Do not claim that a dedicated unprivileged gateway service account is supported
until its D-Bus policy, CDB access, sequence-state ownership, install, upgrade
and recovery paths have been validated on the target Raspberry Pi.

## Project support

Normal installation questions, defect reports and compatibility findings belong
in the
[central community support thread](https://github.com/Nibbels/ioBroker.sanlightmesh/issues/1).
Do not include credentials, Mesh keys or private exports there.

This gateway and the companion adapter are independent community software.
Please do not ask SANlight product support to troubleshoot them.

## Reporting a vulnerability

Open a private GitHub security advisory when available or contact the maintainer
privately. Do not publish credentials, Mesh keys or a private CDB in a public
issue.
