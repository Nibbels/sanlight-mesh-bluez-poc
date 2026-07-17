# MQTT Gateway for SANlight Mesh

A self-contained Raspberry Pi gateway for controlling SANlight EVO Bluetooth
Mesh dimmers through a local MQTT API.

The gateway stays near the lamps and runs BlueZ Mesh, the SANlight protocol
engine, an authenticated Mosquitto broker and the always-on MQTT service. The
companion [`ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh)
adapter connects over the local network. Mesh keys never leave the gateway Pi.

> Independent community project for compatibility with SANlight Mesh. Not
> affiliated with, endorsed by, or an official product of SANlight GmbH. The
> name `SANlight` is used only to identify compatible products, the official app
> and the associated Mesh network.

## Architecture

```text
SANlight lamps
      |
      | Bluetooth Mesh
      v
Gateway Raspberry Pi (this project)
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

Setup **does not change lamp brightness or lamp time**.

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

Read-only refresh keeps two different values separate:

- `maxBrightness` is the configured schedule scaling limit;
- `liveBrightnessRaw` is the lamp's current effective-output field from
  `GetUptimeAndBrightness`.

The additional `liveBrightnessPercentEstimate` is currently calculated as
`liveBrightnessRaw / 10`. That scale is based on observed hardware behavior and
must not be treated as calibrated power, photon flux or PPFD.

The documented topology was validated end to end on real hardware from
2026-07-16 through 2026-07-18, including installation, state adoption,
read-only refresh, reversible brightness writes, retained-command rejection,
deduplication, expiry, coalescing, rate limiting, restart recovery and the
manual lamp-clock workflow. See [docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md)
for the detailed record.

Version `0.3.0` is the current immutable release. The project remains pre-1.0,
so coordinated compatibility changes are documented explicitly in both
repositories.

The read-only current-output percentage was additionally compared with the
SANlight app on 2026-07-17: the gateway value `33.4%` appeared as the app's
rounded `34%`. MQTT API v1 keeps the raw vendor field for validation and
compatibility, while user interfaces should normally present the percentage.

Other SANlight firmware versions, Mesh layouts and network-security designs
require their own validation.

## Lamp-clock handling

MQTT API v1 exposes the last observed lamp clock as whole seconds since
local midnight plus `HH:MM:SS`. Explicit commands can copy the gateway
Raspberry Pi's current local clock or set an arbitrary lamp time. Clock values
are snapshots and are never synchronized automatically. On the validated
two-lamp setup, restoring lamp power reset both internal clocks to `00:00:00`;
an explicit synchronization restored local time. See
[docs/MQTT_API.md](docs/MQTT_API.md).

## Documentation

- [SETUP.md](SETUP.md) — first gateway installation
- [INSTRUCTIONS.md](INSTRUCTIONS.md) — routine operation and maintenance
- [docs/ADVANCED_REFERENCE.md](docs/ADVANCED_REFERENCE.md) — identities, CLI and recovery
- [docs/MQTT_API.md](docs/MQTT_API.md) — MQTT API v1 contract
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — component and repository boundaries
- [SECURITY.md](SECURITY.md) — secrets and network-security boundaries
- [CHANGELOG.md](CHANGELOG.md) — notable changes

Implementation and maintainer references remain in the repository, but are not required for installation or normal operation.

## License

MIT License. See [LICENSE](LICENSE).
