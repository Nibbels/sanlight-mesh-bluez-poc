![Visual overview of SANlight Bluetooth Mesh control via Raspberry Pi](docs/sanlight_mesh_steuerung_ueber_raspberry_pi.png)

# SANlight Mesh BlueZ PoC

Control SANlight EVO Bluetooth Mesh dimmers from a Raspberry Pi with BlueZ and Python.

The repository now contains two validated operating paths:

- a hardened command-line interface for setup, diagnostics, clock handling, MaxBrightness control, blackout and restoration;
- an optional always-on MQTT edge gateway for remote control through Mosquitto, ioBroker or another MQTT client.

## Current validation status

| Area | Status |
|---|---|
| Raspberry Pi OS Lite 64-bit / Debian 13 `trixie` | hardware validated |
| BlueZ 5.82 with `bluetooth-meshd --io generic:hci0` | hardware validated |
| Read-only lamp status and MaxBrightness queries | hardware validated |
| Verified `set-max` with strict readback | hardware validated |
| Explicit blackout and protected restore | hardware validated |
| MQTT v1 gateway with Mosquitto | hardware validated |
| Generic ioBroker MQTT adapter integration | hardware validated |
| Native ioBroker adapter | not implemented yet |

The MQTT gateway was validated with two real SANlight nodes, service and broker restarts, retained-message safety, QoS 1 duplicate handling, TTL expiry, command coalescing, persistent rate limiting, blackout/restore and full Raspberry Pi reboot recovery.

This is operationally validated for the documented installation, but the repository remains a PoC rather than a broadly supported production product. There is no stable release contract or native ioBroker adapter yet, and other SANlight firmware, Mesh layouts, brokers and network-security designs require their own validation.

> **Private data:** `private/SANlightMesh.json`, NetKey, AppKey, DeviceKey, MQTT passwords and local BlueZ state tokens must never be committed, published, pasted into issues, or shared in logs.

## Start here

For a new lamp-side Raspberry Pi:

1. Follow **[SETUP.md](SETUP.md)**.
2. Verify one lamp with a read-only command.
3. Continue with **[INSTRUCTIONS.md](INSTRUCTIONS.md)** for normal operation and troubleshooting.
4. Install the optional remote gateway with **[docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)**.

## Documentation

- **[SETUP.md](SETUP.md)** — minimal first-time installation
- **[INSTRUCTIONS.md](INSTRUCTIONS.md)** — commands, operation, maintenance and troubleshooting
- **[docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)** — validated MQTT gateway installation and operation
- **[docs/MQTT_API.md](docs/MQTT_API.md)** — versioned MQTT v1 contract
- **[docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md)** — validated generic ioBroker MQTT integration
- **[docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md)** — completed hardware validation record and repeatable regression plan
- **[AI_CONTEXT.md](AI_CONTEXT.md)** — architecture, protocol findings, invariants and AI continuation context

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.
