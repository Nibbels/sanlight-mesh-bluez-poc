# Security policy

## Supported status

This is a pre-1.0 community project. Security fixes target the current `main` branch and the most recent tagged release once releases are published.

## Secret boundary

The gateway host is the only component that may possess:

- the SANlight CDB;
- NetKeys, AppKeys and DeviceKeys;
- BlueZ local identity tokens;
- sender sequence state.

The MQTT broker and ioBroker adapter must never receive those values.

## MQTT

Use separate least-privilege users for gateway and automation clients. Commands must be non-retained. Plain MQTT credentials are acceptable only on a trusted isolated LAN. Use TLS when traffic crosses an untrusted segment.

One adapter instance must be restricted to one gateway ID. For separate rooms or facilities, use separate IDs and ACL scopes.

## Local files

- config, CDB and MQTT password files: mode `0600`;
- state directories: mode `0700`;
- do not place private material in the Git checkout when a system configuration path is available;
- do not back up or restore an older sender sequence state over a newer one.

## Diagnostics

Use `sanlight-gateway collect-diagnostics`. Review the text before sharing. Do not attach the CDB, password files, private keys or `.state/` files.

## Reporting a vulnerability

Open a GitHub security advisory when available, or contact the maintainer privately. Do not publish working credentials, Mesh keys or a private CDB in a public issue.

## Service identity

The currently validated pre-1.0 systemd unit runs the gateway as `root` because the existing BlueZ Mesh D-Bus and private state layout were validated with root ownership. The unit still applies `NoNewPrivileges`, restricted address families, a private temporary directory, read-only application/config paths and an explicit writable state path.

Do not claim that a dedicated unprivileged service account is supported until its BlueZ D-Bus policy, CDB access, sequence-state ownership, install, upgrade and recovery paths have been tested on the target Raspberry Pi. Moving to a dedicated account remains a hardening candidate, not a hidden installer side effect.
