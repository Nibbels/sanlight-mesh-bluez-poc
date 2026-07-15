# Interactive gateway installer

## Scope

`scripts/install-gateway.sh` is a low-maintenance deployment helper for an already prepared lamp-side Raspberry Pi.

It does not provision a new SANlight Mesh and it does not replace `SETUP.md`. Before running it, the following must already exist:

- a validated private SANlight CDB;
- control and canonical-sender BlueZ identity state;
- a working `sanlight-meshd-generic.service`;
- a reachable MQTT broker and credentials with suitable ACLs.

The installer never sends brightness or clock writes. The service may perform its configured read-only startup refresh.

## What it does

- asks for gateway ID, CDB, state directory and MQTT settings;
- reads the MQTT password without echoing it;
- writes configuration below `/etc/sanlight-mesh-mqtt-gateway/` with mode `0600`;
- validates the configuration before changing systemd state;
- delegates service installation to the existing validated `install-mqtt-gateway.sh`;
- installs `/usr/local/sbin/sanlight-gateway` as an operational helper;
- runs a read-only doctor report after installation.

The application continues to run from the checked-out release directory. This deliberately avoids a Debian package and keeps updates understandable for a small community project.

The installer does not install or reconfigure an MQTT broker and does not create broker users. Broker placement is independent of the gateway, so users must prepare a reachable broker account and least-privilege ACL first. The wizard stores those existing credentials safely and validates the gateway configuration.

## Run

From the repository root:

```bash
sudo bash scripts/install-gateway.sh
```

Optional non-interactive paths for automation:

```bash
sudo bash scripts/install-gateway.sh \
    --config /etc/sanlight-mesh-mqtt-gateway/gateway.toml \
    --reuse-existing
```

`--reuse-existing` validates and reinstalls an existing config without asking for secrets again.

## Idempotency

Rerunning the installer:

- preserves the existing config unless the operator chooses to replace it;
- creates timestamped backups before overwriting configuration;
- updates `gateway.project_root` and the systemd unit to the current release directory;
- does not reset BlueZ state;
- does not change sequence numbers;
- does not issue lamp write commands.

## Remaining validation

The underlying MQTT gateway is hardware-validated. The new interactive wrapper must still be tested on:

1. a clean supported Raspberry Pi OS image;
2. an upgrade over the current in-repository installation;
3. a broker with TLS;
4. failure paths such as bad password, missing CDB and unavailable broker.

Do not describe the wrapper as generally validated until these tests are complete.
