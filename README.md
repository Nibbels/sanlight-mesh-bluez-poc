# SANlight Mesh MQTT Gateway

A self-contained Raspberry Pi gateway for controlling SANlight EVO Bluetooth
Mesh dimmers from ioBroker.

The gateway Pi stays close to the lamps and runs everything needed on the
SANlight side:

- BlueZ Mesh and the SANlight protocol engine;
- an authenticated local Mosquitto broker;
- an always-on MQTT gateway service;
- protected Mesh identity, sequence and credential storage.

The companion [`ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh)
adapter connects over the local network and creates normal ioBroker devices and
states. Mesh keys never leave the gateway Pi.

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.

## How it fits together

```text
SANlight lamps
      |
      | Bluetooth Mesh
      v
SANlight gateway Raspberry Pi
  BlueZ + gateway + Mosquitto
      ^
      | MQTT over a trusted LAN
      |
ioBroker Raspberry Pi
  ioBroker.sanlightmesh + automation
```

The gateway process connects to its own broker through `127.0.0.1`. ioBroker
connects to a stable LAN IP address or hostname of the gateway Pi.

## Quick start

1. Clone this repository onto a supported Raspberry Pi.
2. Copy the private SANlight export to `private/SANlightMesh.json`.
3. Run:

```bash
sudo bash scripts/install-gateway.sh
```

4. Save the ioBroker broker settings printed at the end.
5. Install the native `ioBroker.sanlightmesh` adapter and create one instance
   for this gateway.

The installer performs the complete lamp-side installation. It installs the
packages, safely prepares the two local BlueZ identities, configures Mosquitto,
creates separate gateway and ioBroker credentials, starts both services and
runs read-only health checks.

It **does not change lamp brightness or lamp time**.

Follow [SETUP.md](SETUP.md) for the complete first installation. Advanced CLI
commands, updates, recovery and troubleshooting are in
[INSTRUCTIONS.md](INSTRUCTIONS.md).

## Multiple gateways

One ioBroker adapter instance manages exactly one physical SANlight gateway:

```text
sanlightmesh.0 -> room-a gateway Pi
sanlightmesh.1 -> room-b gateway Pi
sanlightmesh.2 -> greenhouse gateway Pi
```

Each gateway Pi has its own Mesh state, broker credentials and topic root. This
keeps independent rooms and installations isolated.

## Normal operation

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
sudo sanlight-gateway collect-diagnostics
```

The diagnostics command is designed to omit credentials and Mesh secrets.
Always review its output before sharing it.

## Validation status

The reference installation was validated end to end on real hardware on
2026-07-16:

- Raspberry Pi 3, Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`;
- BlueZ 5.82 with `bluetooth-meshd --io generic:hci0`;
- local Mosquitto 2.0 broker installed by the unified installer;
- missing protected `.state/` files safely reconstructed from matching BlueZ
  identities without re-importing or resetting them;
- `sanlight-meshd-generic.service`, `mosquitto.service` and
  `sanlight-mqtt-gateway.service` healthy after installation;
- native `ioBroker.sanlightmesh` adapter connected from a separate Raspberry Pi 4;
- gateway availability and protocol compatibility reported correctly;
- read-only refresh verified through the complete ioBroker → MQTT → Mesh path;
- reversible MaxBrightness writes verified on two real lamps and independently
  confirmed in the SANlight app;
- both lamps restored to their original 68% test value.

The gateway safety runtime was additionally validated for retained-command
rejection, QoS 1 deduplication, TTL expiry, command coalescing, persistent rate
limiting, blackout/restore and restart recovery. See
[docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md).

This remains a pre-1.0 community project. Other SANlight firmware versions,
Mesh layouts and network-security designs require their own validation.

## Documentation

- [SETUP.md](SETUP.md) — normal end-to-end installation
- [INSTRUCTIONS.md](INSTRUCTIONS.md) — operation, maintenance and advanced recovery
- [docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md) — native ioBroker setup
- [docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md) — gateway and local broker operation
- [docs/MQTT_API.md](docs/MQTT_API.md) — MQTT API v1 contract
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — repository and deployment boundaries
- [docs/INSTALLER.md](docs/INSTALLER.md) — installer design and identity-state matrix
- [docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md) — hardware validation and regression plan
- [SECURITY.md](SECURITY.md) — secret and network-security boundaries
- [AI_CONTEXT.md](AI_CONTEXT.md) — implementation invariants for maintainers and AI tools
