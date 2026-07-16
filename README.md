# SANlight Mesh MQTT Gateway

A self-contained Raspberry Pi gateway for controlling SANlight EVO Bluetooth
Mesh dimmers through a local MQTT API.

The gateway stays near the lamps and runs BlueZ Mesh, the SANlight protocol
engine, an authenticated Mosquitto broker and the always-on MQTT service. The
companion [`ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh)
adapter connects over the local network. Mesh keys never leave the gateway Pi.

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.

## Architecture

```text
SANlight lamps
      |
      | Bluetooth Mesh
      v
SANlight gateway Raspberry Pi
  BlueZ + gateway + Mosquitto
      ^
      | authenticated MQTT on a trusted LAN
      |
ioBroker host
  ioBroker.sanlightmesh adapter
```

The gateway process connects to Mosquitto through `127.0.0.1`. ioBroker uses a
stable LAN IP address or hostname of the gateway Pi.

## Requirements

- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`
- a Raspberry Pi near the SANlight lamps
- a private `SANlightMesh.json` export from the SANlight app
- ioBroker or another MQTT API v1 client on the same trusted LAN

Do not expose MQTT port `1883` to the internet.

## Quick start

```bash
git clone https://github.com/Nibbels/sanlight-mesh-mqtt-gateway.git
cd sanlight-mesh-mqtt-gateway
```

Copy the private SANlight export to `private/SANlightMesh.json`, then run:

```bash
sudo bash scripts/install-gateway.sh
```

The installer:

- validates the private export and runs the offline safety tests;
- safely imports or adopts the two required BlueZ identities;
- installs and configures BlueZ Mesh, Mosquitto and the MQTT gateway;
- creates separate scoped credentials for the gateway and ioBroker;
- starts the services and performs read-only health checks.

It **does not change lamp brightness or lamp time**.

Continue with [SETUP.md](SETUP.md) for the complete gateway installation. When
it finishes, use the adapter repository's README for ioBroker installation and
the first read-only test.

## Normal operation

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
sudo sanlight-gateway collect-diagnostics
```

Review diagnostic output before sharing it. The command is designed to omit
credentials and Mesh secrets, but local hostnames and topology details may still
be visible.

## Multiple gateways

Use one gateway Pi and one adapter instance per independent SANlight Mesh. Each
gateway has its own private Mesh state, credentials, gateway ID and MQTT topic
root.

## Safety and status

Normal MaxBrightness writes are restricted to `20..100%`. Zero is available
only through the explicit blackout workflow. Commands are non-retained, expire
quickly and are verified through lamp readback where supported.

The documented topology was validated end to end on real hardware on
2026-07-16, including installation, state adoption, read-only refresh,
reversible brightness writes, retained-command rejection, deduplication,
expiry, coalescing, rate limiting and restart recovery. See
[docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md) for the detailed record.

This remains a pre-1.0 community project. Other SANlight firmware versions,
Mesh layouts and network-security designs require their own validation.

## Documentation

- [SETUP.md](SETUP.md) — first gateway installation
- [INSTRUCTIONS.md](INSTRUCTIONS.md) — advanced operation, maintenance and recovery
- [docs/MQTT_API.md](docs/MQTT_API.md) — MQTT API v1 contract
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — component and repository boundaries
- [SECURITY.md](SECURITY.md) — secrets and network-security boundaries
- [CHANGELOG.md](CHANGELOG.md) — notable changes

Maintainer and implementation references remain in `docs/` and
[AI_CONTEXT.md](AI_CONTEXT.md), but are not required for normal installation.

## License

MIT License. See [LICENSE](LICENSE).
