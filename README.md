# SANlight Mesh MQTT Gateway

A local, community-built Bluetooth Mesh edge gateway for SANlight EVO dimmers. The Raspberry Pi remains close to the lamps, keeps all Mesh credentials local, and exposes a small versioned MQTT API for ioBroker or another automation system.

![Multiple SANlight Mesh MQTT gateways connected through an MQTT broker to native ioBroker integration](docs/sanlight_mesh_mqtt_iobroker_architecture.png)

The **MQTT gateway is the product path**. The hardened CLI remains its authoritative Mesh transaction engine and provides advanced diagnostics, maintenance, replay recovery, clock commands, MaxBrightness control, blackout and restore.

## One-command installation

After cloning the repository and placing the private SANlight export at `private/SANlightMesh.json`, run:

```bash
sudo bash scripts/install-gateway.sh
```

The installer performs the complete local deployment:

- validates the private CDB and runs the offline safety suite;
- installs BlueZ, Python and MQTT dependencies;
- installs the exclusive `generic:hci0` Mesh service;
- safely adopts existing BlueZ identities or imports genuinely absent identities;
- creates or reuses protected MQTT configuration and credentials;
- installs and starts the MQTT gateway service;
- runs read-only health checks.

It never changes lamp brightness or lamp time. A gateway startup may perform the configured **read-only** refresh.

When `.state/` is missing but the exact CDB-derived BlueZ identity still exists, the installer validates its UUID path, DeviceKey, unicast address, token and IV Index before reconstructing the protected project state. It never identifies an identity through optional fields such as `appKeys` and never re-imports over ambiguous state.

See **[SETUP.md](SETUP.md)** for the minimal clean-host procedure and **[INSTRUCTIONS.md](INSTRUCTIONS.md)** for operation, updates, recovery and advanced flags.

## Deployment model

```text
SANlight lamps
      |
      | Bluetooth Mesh
      v
SANlight gateway Raspberry Pi
      |
      | MQTT v1
      v
Broker / ioBroker host
```

Each physical gateway or grow room should use its own `gateway.id`, broker ACL scope and native ioBroker adapter instance. The companion adapter is maintained separately in [`Nibbels/ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh).

## Operations

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
sudo sanlight-gateway collect-diagnostics
```

The diagnostics bundle is intentionally redacted. Never publish the private CDB, `.state/`, `/var/lib/bluetooth/mesh`, password files, NetKey, AppKey, DeviceKeys or BlueZ tokens.

## Current validation status

| Area | Status |
|---|---|
| Raspberry Pi OS Lite 64-bit / Debian 13 `trixie` | hardware validated |
| BlueZ 5.82 with `bluetooth-meshd --io generic:hci0` | hardware validated |
| Read-only lamp and MaxBrightness queries | hardware validated |
| Verified `set-max`, blackout and protected restore | hardware validated |
| MQTT v1 gateway with Mosquitto and generic ioBroker integration | hardware validated |
| End-to-end installer and missing-state adoption | implemented; target-host validation required |
| Native `ioBroker.sanlightmesh` adapter | maintained in separate repository |

This remains a pre-1.0 community project. Other firmware versions, Mesh layouts, brokers and network-security designs require separate validation.

## Documentation

- **[SETUP.md](SETUP.md)** — minimal end-to-end installation
- **[INSTRUCTIONS.md](INSTRUCTIONS.md)** — operation, updates, recovery and advanced flags
- **[docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)** — gateway operation and broker details
- **[docs/MQTT_API.md](docs/MQTT_API.md)** — versioned MQTT v1 contract
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — deployment boundaries
- **[docs/INSTALLER.md](docs/INSTALLER.md)** — installer design and state matrix
- **[docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md)** — ioBroker integration
- **[docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md)** — validation record and regression plan
- **[SECURITY.md](SECURITY.md)** — security model
- **[AI_CONTEXT.md](AI_CONTEXT.md)** — maintainer and AI continuation context

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.
