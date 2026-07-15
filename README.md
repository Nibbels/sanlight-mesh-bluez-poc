# SANlight Mesh MQTT Gateway

A local, community-built Bluetooth Mesh gateway for SANlight EVO dimmers.
The Raspberry Pi remains close to the lamps, keeps all Mesh credentials local,
runs its own authenticated Mosquitto broker, and exposes a small versioned MQTT
API for ioBroker or another automation system.

The **MQTT gateway is the product path**. The hardened CLI remains its
authoritative Mesh transaction engine and provides advanced diagnostics,
maintenance, replay recovery, clock commands, MaxBrightness control, blackout
and restore.

## One-command installation

After cloning the repository and placing the private SANlight export at
`private/SANlightMesh.json`, run:

```bash
sudo bash scripts/install-gateway.sh
```

The installer performs the complete lamp-side deployment:

- validates the private CDB and runs the offline safety suite;
- installs BlueZ, Python, Paho MQTT, Mosquitto and MQTT client tools;
- installs the exclusive `generic:hci0` Mesh service;
- safely adopts existing BlueZ identities or imports genuinely absent identities;
- creates a local authenticated broker with gateway-scoped ACLs;
- creates protected credentials for the local gateway and remote ioBroker client;
- installs and starts the MQTT gateway service;
- prints the settings required by the ioBroker adapter;
- runs read-only health checks.

It never changes lamp brightness or lamp time. A gateway startup may perform the
configured **read-only** refresh. The installer preserves compatible existing
Mesh state and stops safely when the local identity state is inconsistent.

See **[SETUP.md](SETUP.md)** for the minimal clean-host procedure and
**[INSTRUCTIONS.md](INSTRUCTIONS.md)** for operation, updates, recovery and
advanced maintenance.

## Default deployment model

```text
SANlight lamps
      |
      | Bluetooth Mesh
      v
SANlight-PoCe Raspberry Pi
  BlueZ Mesh + gateway + Mosquitto
      ^
      | MQTT over the trusted LAN
      |
ioBroker Raspberry Pi
  ioBroker.sanlightmesh adapter + automation
```

The gateway process connects to its broker through `127.0.0.1`. The ioBroker
adapter connects to a stable LAN IP or hostname of the SANlight gateway Pi.

## Multiple SANlight gateways

Multiple independent SANlight gateway Pis are an intended deployment:

```text
sanlightmesh.0 -> SANlight-PoCe room-a -> gateway.id room-a
sanlightmesh.1 -> SANlight-PoCe room-b -> gateway.id room-b
sanlightmesh.2 -> SANlight-PoCe greenhouse -> gateway.id greenhouse
```

One native ioBroker adapter instance manages exactly one configured gateway.
Each instance connects to that gateway Pi's broker and subscribes only to the
exact `sanlightmesh/v1/<gateway-id>/...` topic root. This prevents lamps from
separate rooms or buildings from being combined accidentally.

The companion adapter is maintained separately in
[`Nibbels/ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh).

## Operations

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
sudo sanlight-gateway collect-diagnostics
```

The diagnostics bundle is intentionally redacted. Never publish the private
CDB, `.state/`, `/var/lib/bluetooth/mesh`, password files, NetKey, AppKey,
DeviceKeys or BlueZ tokens.

## Current validation status

| Area | Status |
|---|---|
| Raspberry Pi OS Lite 64-bit / Debian 13 `trixie` | hardware validated |
| BlueZ 5.82 with `bluetooth-meshd --io generic:hci0` | hardware validated |
| Read-only lamp and MaxBrightness queries | hardware validated |
| Verified `set-max`, blackout and protected restore | hardware validated |
| MQTT v1 gateway with Mosquitto and generic ioBroker integration | hardware validated |
| Unified local-broker installer and missing-state adoption | implemented; target-host validation required |
| Native `ioBroker.sanlightmesh` adapter | maintained in separate repository |

This remains a pre-1.0 community project. Other firmware versions, Mesh layouts
and network-security designs require separate validation.

## Documentation

- **[SETUP.md](SETUP.md)** — minimal end-to-end installation
- **[INSTRUCTIONS.md](INSTRUCTIONS.md)** — operation, updates, recovery and advanced maintenance
- **[docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)** — gateway and local broker operation
- **[docs/MQTT_API.md](docs/MQTT_API.md)** — versioned MQTT v1 contract
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — deployment and multi-instance boundaries
- **[docs/INSTALLER.md](docs/INSTALLER.md)** — installer design and state matrix
- **[docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md)** — ioBroker integration
- **[docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md)** — validation record and regression plan
- **[SECURITY.md](SECURITY.md)** — security model
- **[AI_CONTEXT.md](AI_CONTEXT.md)** — maintainer and AI continuation context

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.
